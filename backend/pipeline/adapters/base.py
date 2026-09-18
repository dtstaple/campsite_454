"""
The source adapter contract.

Every source implements the same three steps and nothing else:

    fetch(aoi)        pull raw data for an area of interest
    normalize(raw)    convert to canonical field dicts
    load(records)     write to PostGIS, idempotently

fetch and normalize are abstract because they are the only genuinely per-source logic.
Everything else is a shared concern and lives here, so it exists once instead of being
copy-pasted into four adapters:

    - provenance: an IngestRun is opened before fetch and closed after load with the
      record count and a success/partial/failed status
    - last_run is stamped on every row written, giving per-record provenance
    - idempotent upsert keyed on (source, source_id), so a rerun updates rather than
      duplicates
    - reprojection to EPSG:4326 from the adapter's declared source_srid, so NHD (4269)
      and PAD-US (5070) adapters declare a number instead of reimplementing transform
    - geometry validation, single-to-multi promotion, and a clear error when a source
      hands back a geometry the target column cannot hold

An adapter therefore declares four attributes and writes two methods. Adding a source
never requires editing this file or the registry.
"""

from abc import ABC, abstractmethod
from typing import Any

from django.contrib.gis.geos import GEOSGeometry, MultiLineString, MultiPoint, MultiPolygon
from django.db import transaction
from django.utils import timezone

from geodata.models import IngestRun
from pipeline.aoi import AreaOfInterest

# How many skip reasons to keep in IngestRun.notes before truncating.
MAX_LOGGED_SKIPS = 20

# Sources are inconsistent about single vs multi geometry. A single geometry fits inside
# a Multi container, so promote rather than reject; the reverse is a genuine error.
_PROMOTIONS = {
    "MULTIPOINT": ("Point", MultiPoint),
    "MULTILINESTRING": ("LineString", MultiLineString),
    "MULTIPOLYGON": ("Polygon", MultiPolygon),
}


class AdapterError(Exception):
    """Base for anything the framework rejects in an adapter or its output."""


class AdapterConfigurationError(AdapterError):
    """An adapter class is missing a required attribute."""


class GeometryTypeMismatch(AdapterError):
    """A source returned a geometry the target column cannot hold."""


class SourceAdapter(ABC):
    """Base class for all source adapters.

    Subclasses declare:
        name: registry key and CLI argument, e.g. "osm"
        source: the geodata SourceRecord.Source value written to each row
        model: the geodata model to write into
        source_srid: the projection the source delivers, if not already 4326

    and implement fetch() and normalize().
    """

    name: str = ""
    source: str = ""
    model: Any = None
    source_srid: int = AreaOfInterest.SRID

    def __init__(self):
        missing = [attr for attr in ("name", "source", "model") if not getattr(self, attr, None)]
        if missing:
            raise AdapterConfigurationError(f"{type(self).__name__} must set: {', '.join(missing)}")

    # --- the two methods an adapter actually writes -----------------------------------

    @abstractmethod
    def fetch(self, aoi: AreaOfInterest) -> Any:
        """Pull raw data for `aoi`. Return whatever shape the source gives back."""

    @abstractmethod
    def normalize(self, raw: Any) -> list[dict]:
        """Convert raw source data into dicts of model field names.

        Each dict needs `source_id` and `geom`; `geom` may be in the adapter's
        source_srid and may be a single geometry where the column expects a Multi.
        The framework handles reprojection, promotion, and validation.
        """

    # --- framework-owned ---------------------------------------------------------------

    @classmethod
    def target_geom_type(cls) -> str:
        """The geometry type the model's geom column accepts, e.g. "MULTIPOLYGON"."""
        return cls.model._meta.get_field("geom").geom_type

    @classmethod
    def upsert_update_fields(cls) -> list[str]:
        """Columns to overwrite on conflict.

        Everything except the identity of the row and when it was first seen: the upsert
        key must not change, and created_at should keep the original ingest time.
        """
        skip = {"id", "source", "source_id", "created_at"}
        return [f.name for f in cls.model._meta.concrete_fields if f.name not in skip]

    def run_parameters(self, aoi: AreaOfInterest) -> dict:
        """What gets recorded in IngestRun.parameters. Override to add source specifics."""
        return {
            "bbox": list(aoi.bbox),
            "states": list(aoi.states),
            "source_srid": self.source_srid,
        }

    def prepare_geometry(self, geom: Any) -> GEOSGeometry:
        """Reproject to 4326 and coerce to the target column's geometry type."""
        if not isinstance(geom, GEOSGeometry):
            raise GeometryTypeMismatch(
                f"{self.name}: expected a GEOS geometry, got {type(geom).__name__}"
            )

        if geom.srid is None:
            geom = geom.clone()
            geom.srid = self.source_srid

        if geom.srid != AreaOfInterest.SRID:
            geom = geom.transform(AreaOfInterest.SRID, clone=True)

        target = self.target_geom_type()
        if target == "GEOMETRY":
            return geom

        actual = geom.geom_type
        if actual.upper() == target:
            return geom

        promotable = _PROMOTIONS.get(target)
        if promotable and actual == promotable[0]:
            container = promotable[1]
            return container(geom, srid=geom.srid)

        raise GeometryTypeMismatch(
            f"{self.name}: {self.model.__name__}.geom is {target} but the source returned "
            f"{actual}. Fix normalize() to emit {target}, or point this adapter at a model "
            "whose geometry column matches."
        )

    @transaction.atomic
    def load(self, records: list[dict], run: IngestRun) -> tuple[int, list[str]]:
        """Upsert `records`, stamping each with this run. Returns (written, skipped)."""
        objs = []
        skipped: list[str] = []

        for index, record in enumerate(records):
            fields = dict(record)
            source_id = fields.pop("source_id", None)
            if not source_id:
                skipped.append(f"record {index}: missing source_id")
                continue

            geom = fields.pop("geom", None)
            if geom is None:
                skipped.append(f"{source_id}: missing geom")
                continue

            prepared = self.prepare_geometry(geom)
            if not prepared.valid:
                skipped.append(f"{source_id}: invalid geometry ({prepared.valid_reason})")
                continue

            # source and last_run are the framework's to set, not the adapter's.
            fields.pop("source", None)
            fields.pop("last_run", None)

            objs.append(
                self.model(
                    source=self.source,
                    source_id=source_id,
                    geom=prepared,
                    last_run=run,
                    **fields,
                )
            )

        if objs:
            self.model.objects.bulk_create(
                objs,
                update_conflicts=True,
                unique_fields=["source", "source_id"],
                update_fields=self.upsert_update_fields(),
            )

        return len(objs), skipped

    def run(self, aoi: AreaOfInterest) -> IngestRun:
        """fetch -> normalize -> load, wrapped in provenance. Returns the IngestRun."""
        run = IngestRun.objects.create(
            source=self.source,
            region=aoi.name,
            started_at=timezone.now(),
            # Pessimistic: if this process is killed mid-run the row says failed rather
            # than claiming a success that never happened.
            status=IngestRun.Status.FAILED,
            parameters=self.run_parameters(aoi),
        )

        try:
            raw = self.fetch(aoi)
            records = self.normalize(raw)
            written, skipped = self.load(records, run)
        except Exception as exc:
            run.finished_at = timezone.now()
            run.status = IngestRun.Status.FAILED
            run.notes = f"{type(exc).__name__}: {exc}"
            run.save(update_fields=["finished_at", "status", "notes"])
            raise

        run.record_count = written
        run.finished_at = timezone.now()
        run.status = IngestRun.Status.PARTIAL if skipped else IngestRun.Status.SUCCESS
        if skipped:
            shown = skipped[:MAX_LOGGED_SKIPS]
            more = len(skipped) - len(shown)
            run.notes = f"Skipped {len(skipped)} record(s):\n" + "\n".join(shown)
            if more:
                run.notes += f"\n... and {more} more"
        run.save(update_fields=["record_count", "finished_at", "status", "notes"])
        return run

    def __str__(self):
        return f"{self.name} -> {self.model.__name__}"
