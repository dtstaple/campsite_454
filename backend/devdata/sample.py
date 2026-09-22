"""
The committed sample dataset: what it covers, where it lives, and how it is produced.

The full database is ~92k features and far too large to commit, so every environment that
just needs *something* on the map -- a new laptop, a second database, CI -- loads this small
Django fixture instead. It is a fixture rather than a pg_dump because loaddata needs no
network, no API key, and no Postgres client tools (which Windows machines usually lack),
and a JSON file diffs readably in review.

The fixture is produced by `manage.py build_sample`, which runs the real adapters against
SAMPLE_AOI and then calls dump_sample(). Geometries are clipped to the AOI and written at
6 decimal places (~10 cm) so a trail or PAD-US polygon that runs for kilometres past the
box does not drag its full length into the repo. Attributes are not recomputed, so a
clipped trail's length_m still describes the whole trail. `raw` is kept: it is the source payload
the typed columns were derived from, and dropping it would make the sample less faithful
to what the pipeline really writes.
"""

import json
from pathlib import Path

from django.contrib.gis.geos import (
    GeometryCollection,
    GEOSGeometry,
    MultiLineString,
    MultiPolygon,
    WKTWriter,
)
from django.core import serializers

from geodata.models import Campsite, IngestRun, PublicLand, Trail, WaterFeature
from pipeline.aoi import AreaOfInterest

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample.json"

# Crawford Notch in the White Mountains, roughly 5 x 7 km. Chosen because it has every
# layer in a small area: several PAD-US parcels, the Appalachian Trail and its side trails,
# the Saco River, and ponds. An Adirondack box was tried first, but the one PAD-US parcel
# there (the Forest Preserve) has invalid geometry and the adapter skips it, leaving no
# public land in the sample.
SAMPLE_AOI = AreaOfInterest(
    name="sample-crawford-notch",
    label="Crawford Notch sample",
    bbox=(-71.44, 44.17, -71.38, 44.23),
    states=("NH",),
    notes="Committed dev sample. Built by manage.py build_sample; loaded by manage.py seed.",
)

# IngestRun first: every feature row points at one through last_run.
SAMPLE_MODELS = [IngestRun, PublicLand, Trail, WaterFeature, Campsite]
FEATURE_MODELS = [PublicLand, Trail, WaterFeature, Campsite]

# Keyless sources. RIDB is added by build_sample only when RIDB_API_KEY is set.
KEYLESS_ADAPTERS = ["padus", "osm-trails", "nhd-flowlines", "nhd-waterbodies"]

COORDINATE_PRECISION = 6

_WKT = WKTWriter(precision=COORDINATE_PRECISION, trim=True)

# Clipping can change a geometry's dimension at the edges (a polygon touching the box
# at one corner intersects it in a point). Keep only parts the column can hold.
_KEEP = {
    "MULTIPOLYGON": ("Polygon", MultiPolygon),
    "MULTILINESTRING": ("LineString", MultiLineString),
    "POINT": ("Point", None),
}


def feature_count() -> int:
    """Total feature rows across every geodata layer."""
    return sum(model.objects.count() for model in FEATURE_MODELS)


def clip(geom: GEOSGeometry, target: str, box: GEOSGeometry) -> GEOSGeometry | None:
    """Clip `geom` to `box`, returning something column type `target` accepts, or None."""
    clipped = geom.intersection(box)
    if clipped.empty:
        return None
    if target == "GEOMETRY":
        return clipped

    single_type, container = _KEEP[target]
    parts = list(clipped) if isinstance(clipped, GeometryCollection) else [clipped]
    singles = [part for part in parts if part.geom_type == single_type]
    if not singles:
        return None
    if container is None:
        return singles[0]
    return container(*singles, srid=geom.srid)


def _ewkt(geom: GEOSGeometry) -> str:
    return f"SRID={geom.srid};{_WKT.write(geom).decode()}"


def dump_sample(path: Path = FIXTURE_PATH, aoi: AreaOfInterest = SAMPLE_AOI) -> dict:
    """Write every IngestRun and feature row in the database to `path` as a fixture.

    Geometries are clipped to `aoi` and rows left empty by clipping are dropped. Returns
    {model label: rows written} so the caller can report it.
    """
    box = aoi.as_polygon()
    entries: list[dict] = []
    counts: dict[str, int] = {}

    for model in SAMPLE_MODELS:
        label = model._meta.label_lower
        counts[label] = 0
        has_geom = model is not IngestRun
        target = model._meta.get_field("geom").geom_type if has_geom else None

        for obj in model.objects.order_by("pk"):
            if has_geom:
                geom = clip(obj.geom, target, box)
                if geom is None:
                    continue
            entry = json.loads(serializers.serialize("json", [obj]))[0]
            if has_geom:
                entry["fields"]["geom"] = _ewkt(geom)
            entries.append(entry)
            counts[label] += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    # One entry per line keeps diffs reviewable without the bloat of full indentation.
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("[\n")
        fh.write(",\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in entries))
        fh.write("\n]\n")
    return counts
