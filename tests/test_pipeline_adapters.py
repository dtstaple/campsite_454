"""
Ingestion framework tests.

Every adapter in this file is a throwaway defined in the test suite, never shipped code.
That is the point: if a source can be added here -- registered, run end to end, written to
PostGIS -- without editing base.py, registry.py, or ingest.py, then the acceptance
criterion "adding a source means writing one adapter, with no changes to the framework"
actually holds rather than being asserted.

Real adapters (RIDB, OSM, NHD, PAD-US) are TM05-13.
"""

from io import StringIO

import pytest
from django.contrib.gis.geos import LineString, Point, Polygon
from django.core.management import call_command
from django.core.management.base import CommandError

from geodata.models import Campsite, IngestRun, PublicLand, Trail, WaterFeature
from pipeline.adapters import (
    GeometryTypeMismatch,
    SourceAdapter,
    get_adapter,
    list_adapters,
)
from pipeline.adapters.base import AdapterConfigurationError
from pipeline.adapters.registry import UnknownAdapterError
from pipeline.aoi import AreaOfInterest

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

ADK = AreaOfInterest(
    name="adirondacks",
    label="Adirondack Park",
    bbox=(-75.40, 43.00, -73.30, 44.90),
    states=("NY",),
)

VALID_RING = Polygon(
    ((-75.0, 43.0), (-74.0, 43.0), (-74.0, 44.0), (-75.0, 44.0), (-75.0, 43.0)),
    srid=4326,
)
# Self-intersecting ring: right geometry type, invalid geometry.
BOWTIE = Polygon(
    ((-75.0, 43.0), (-74.0, 44.0), (-74.0, 43.0), (-75.0, 44.0), (-75.0, 43.0)),
    srid=4326,
)


class FakeCampsiteAdapter(SourceAdapter):
    """Two fake campsites. Declares four attributes, writes two methods, nothing else."""

    name = "fake-campsites"
    source = Campsite.Source.RIDB
    model = Campsite

    def fetch(self, aoi):
        return [
            {"id": "fake-1", "lon": -74.05, "lat": 44.11, "title": "Marcy Dam"},
            {"id": "fake-2", "lon": -74.00, "lat": 44.05, "title": "Lake Colden"},
        ]

    def normalize(self, raw):
        return [
            {
                "source_id": row["id"],
                "name": row["title"],
                "geom": Point(row["lon"], row["lat"], srid=4326),
                "site_type": Campsite.SiteType.PRIMITIVE,
            }
            for row in raw
        ]


# --- the criterion-5 proof ------------------------------------------------------------


def test_a_new_adapter_runs_end_to_end_with_no_framework_changes(clean_registry):
    clean_registry.register(FakeCampsiteAdapter)

    assert list_adapters() == ["fake-campsites"]
    assert get_adapter("fake-campsites") is FakeCampsiteAdapter

    run = FakeCampsiteAdapter().run(ADK)

    assert run.status == IngestRun.Status.SUCCESS
    assert run.record_count == 2
    assert run.region == "adirondacks"
    assert run.finished_at is not None
    assert run.parameters["bbox"] == list(ADK.bbox)
    assert run.parameters["states"] == ["NY"]

    assert Campsite.objects.count() == 2
    site = Campsite.objects.get(source_id="fake-1")
    assert site.name == "Marcy Dam"
    assert site.source == Campsite.Source.RIDB
    assert site.geom.srid == 4326
    assert site.last_run_id == run.pk


# --- idempotency ----------------------------------------------------------------------


def test_running_twice_updates_rows_instead_of_duplicating(clean_registry):
    clean_registry.register(FakeCampsiteAdapter)
    adapter = FakeCampsiteAdapter()

    first = adapter.run(ADK)
    second = adapter.run(ADK)

    assert first.pk != second.pk
    assert Campsite.objects.count() == 2, "upsert on (source, source_id) did not dedupe"

    site = Campsite.objects.get(source_id="fake-1")
    assert site.last_run_id == second.pk, "last_run should point at the most recent run"


def test_rerunning_picks_up_changed_source_data(clean_registry):
    class DriftingAdapter(FakeCampsiteAdapter):
        name = "drifting"
        title = "Original Name"

        def normalize(self, raw):
            return [
                {
                    "source_id": "only-one",
                    "name": self.title,
                    "geom": Point(-74.0, 44.0, srid=4326),
                }
            ]

    clean_registry.register(DriftingAdapter)

    DriftingAdapter().run(ADK)
    DriftingAdapter.title = "Renamed Upstream"
    DriftingAdapter().run(ADK)

    assert Campsite.objects.count() == 1
    assert Campsite.objects.get().name == "Renamed Upstream"


# --- reprojection ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "srid",
    [
        pytest.param(4269, id="nhd-nad83"),
        pytest.param(5070, id="padus-albers"),
    ],
)
def test_geometry_is_reprojected_from_the_declared_source_srid(clean_registry, srid):
    """An adapter declares a projection; it never calls transform itself."""
    original = Point(-74.05, 44.11, srid=4326)
    projected = original.transform(srid, clone=True)
    assert projected.srid == srid

    class ProjectedAdapter(SourceAdapter):
        name = f"projected-{srid}"
        source = Campsite.Source.NHD
        model = Campsite
        source_srid = srid

        def fetch(self, aoi):
            return [None]

        def normalize(self, raw):
            return [{"source_id": "p1", "geom": projected.clone()}]

    clean_registry.register(ProjectedAdapter)
    ProjectedAdapter().run(ADK)

    stored = Campsite.objects.get(source_id="p1")
    assert stored.geom.srid == 4326
    assert stored.geom.x == pytest.approx(original.x, abs=1e-6)
    assert stored.geom.y == pytest.approx(original.y, abs=1e-6)


def test_geometry_with_no_srid_is_assumed_to_be_the_declared_source_srid(clean_registry):
    naive = Point(-74.05, 44.11)
    assert naive.srid is None

    class NaiveAdapter(SourceAdapter):
        name = "naive"
        source = Campsite.Source.RIDB
        model = Campsite
        source_srid = 4326

        def fetch(self, aoi):
            return [None]

        def normalize(self, raw):
            return [{"source_id": "n1", "geom": naive.clone()}]

    clean_registry.register(NaiveAdapter)
    NaiveAdapter().run(ADK)

    assert Campsite.objects.get(source_id="n1").geom.srid == 4326


# --- geometry coercion and validation -------------------------------------------------


def test_a_single_geometry_is_promoted_into_its_multi_container(clean_registry):
    line = LineString((-74.05, 44.11), (-74.04, 44.12), srid=4326)

    class SingleLineAdapter(SourceAdapter):
        name = "single-line"
        source = Trail.Source.OSM
        model = Trail

        def fetch(self, aoi):
            return [None]

        def normalize(self, raw):
            return [{"source_id": "t1", "geom": line.clone(), "osm_node_ids": [1, 2]}]

    clean_registry.register(SingleLineAdapter)
    SingleLineAdapter().run(ADK)

    trail = Trail.objects.get(source_id="t1")
    assert trail.geom.geom_type == "MultiLineString"
    assert trail.geom.num_geom == 1


def test_wrong_geometry_type_fails_loudly_and_names_both_types(clean_registry):
    class PointIntoPolygonAdapter(SourceAdapter):
        name = "mismatched"
        source = PublicLand.Source.PADUS
        model = PublicLand

        def fetch(self, aoi):
            return [None]

        def normalize(self, raw):
            return [{"source_id": "b1", "geom": Point(-74.0, 44.0, srid=4326)}]

    clean_registry.register(PointIntoPolygonAdapter)

    with pytest.raises(GeometryTypeMismatch) as err:
        PointIntoPolygonAdapter().run(ADK)

    message = str(err.value)
    assert "MULTIPOLYGON" in message
    assert "Point" in message

    run = IngestRun.objects.get()
    assert run.status == IngestRun.Status.FAILED
    assert "GeometryTypeMismatch" in run.notes
    assert PublicLand.objects.count() == 0


def test_invalid_geometry_is_skipped_and_the_run_is_marked_partial(clean_registry):
    class MixedQualityAdapter(SourceAdapter):
        name = "mixed"
        source = PublicLand.Source.PADUS
        model = PublicLand

        def fetch(self, aoi):
            return [None]

        def normalize(self, raw):
            return [
                {"source_id": "good", "geom": VALID_RING.clone()},
                {"source_id": "self-intersecting", "geom": BOWTIE.clone()},
                {"source_id": "", "geom": VALID_RING.clone()},
                {"source_id": "no-geometry"},
            ]

    clean_registry.register(MixedQualityAdapter)
    run = MixedQualityAdapter().run(ADK)

    assert run.status == IngestRun.Status.PARTIAL
    assert run.record_count == 1
    assert PublicLand.objects.count() == 1
    assert PublicLand.objects.get().source_id == "good"

    assert "self-intersecting" in run.notes
    assert "missing source_id" in run.notes
    assert "no-geometry: missing geom" in run.notes


# --- provenance on failure ------------------------------------------------------------


def test_a_failed_run_still_records_an_ingestrun_with_failed_status(clean_registry):
    class BrokenUpstreamAdapter(SourceAdapter):
        name = "broken"
        source = Campsite.Source.OSM
        model = Campsite

        def fetch(self, aoi):
            raise RuntimeError("upstream returned 503")

        def normalize(self, raw):  # pragma: no cover - never reached
            return []

    clean_registry.register(BrokenUpstreamAdapter)

    with pytest.raises(RuntimeError, match="upstream returned 503"):
        BrokenUpstreamAdapter().run(ADK)

    run = IngestRun.objects.get()
    assert run.status == IngestRun.Status.FAILED
    assert run.region == "adirondacks"
    assert run.record_count == 0
    assert run.finished_at is not None
    assert "upstream returned 503" in run.notes
    assert Campsite.objects.count() == 0


# --- registry -------------------------------------------------------------------------


def test_unknown_source_names_what_is_registered(clean_registry):
    clean_registry.register(FakeCampsiteAdapter)

    with pytest.raises(UnknownAdapterError) as err:
        get_adapter("does-not-exist")

    message = str(err.value)
    assert "does-not-exist" in message
    assert "fake-campsites" in message


def test_two_adapters_cannot_claim_the_same_name(clean_registry):
    clean_registry.register(FakeCampsiteAdapter)

    class Impostor(FakeCampsiteAdapter):
        pass

    with pytest.raises(ValueError, match="already taken"):
        clean_registry.register(Impostor)


def test_an_adapter_without_a_name_cannot_register(clean_registry):
    class Nameless(FakeCampsiteAdapter):
        name = ""

    with pytest.raises(ValueError, match="non-empty `name`"):
        clean_registry.register(Nameless)


def test_an_adapter_missing_required_attributes_fails_on_construction():
    class Incomplete(SourceAdapter):
        name = "incomplete"

        def fetch(self, aoi):  # pragma: no cover - never constructed
            return []

        def normalize(self, raw):  # pragma: no cover - never constructed
            return []

    with pytest.raises(AdapterConfigurationError, match="source, model"):
        Incomplete()


# --- management command ---------------------------------------------------------------


def test_command_runs_any_registered_adapter_against_any_region(clean_registry):
    clean_registry.register(FakeCampsiteAdapter)
    out = StringIO()

    call_command("ingest", "fake-campsites", "adirondacks", stdout=out)

    output = out.getvalue()
    assert "2 record(s)" in output
    assert Campsite.objects.count() == 2


def test_command_lists_sources_and_regions(clean_registry):
    clean_registry.register(FakeCampsiteAdapter)

    sources = StringIO()
    call_command("ingest", "--list-sources", stdout=sources)
    assert "fake-campsites" in sources.getvalue()

    regions = StringIO()
    call_command("ingest", "--list-regions", stdout=regions)
    listing = regions.getvalue()
    for name in ("adirondacks", "white-mountains-nh", "green-mountains-vt", "maine"):
        assert name in listing


def test_command_fails_usefully_on_unknown_names(clean_registry):
    clean_registry.register(FakeCampsiteAdapter)

    with pytest.raises(CommandError, match="Unknown source 'nope'"):
        call_command("ingest", "nope", "adirondacks")

    with pytest.raises(CommandError, match="Unknown region 'atlantis'"):
        call_command("ingest", "fake-campsites", "atlantis")

    with pytest.raises(CommandError, match="Both <source> and <region> are required"):
        call_command("ingest")


def test_a_generic_geometry_column_accepts_mixed_types_without_promotion(clean_registry):
    """WaterFeature.geom is a bare GeometryField, which is the case NHD needs.

    NHD delivers streams as lines and lakes as polygons in the same dataset, in NAD83.
    Both must land in one column, reprojected, with their own geometry type intact --
    not coerced into a Multi container the way a typed column would coerce them.
    """
    flowline = LineString((-74.05, 44.11), (-74.04, 44.12), srid=4326)
    waterbody = VALID_RING.clone()

    class MixedWaterAdapter(SourceAdapter):
        name = "mixed-water"
        source = WaterFeature.Source.NHD
        model = WaterFeature
        source_srid = 4269  # NHD's native projection, as the real adapter will declare

        def fetch(self, aoi):
            return [None]

        def normalize(self, raw):
            return [
                {
                    "source_id": "nhd-flowline-1",
                    "geom": flowline.transform(4269, clone=True),
                    "feature_type": WaterFeature.FeatureType.STREAM,
                    "perennial": True,
                },
                {
                    "source_id": "nhd-waterbody-1",
                    "geom": waterbody.transform(4269, clone=True),
                    "feature_type": WaterFeature.FeatureType.LAKE,
                    "perennial": None,
                },
            ]

    clean_registry.register(MixedWaterAdapter)
    run = MixedWaterAdapter().run(ADK)

    assert run.status == IngestRun.Status.SUCCESS
    assert run.record_count == 2

    stream = WaterFeature.objects.get(source_id="nhd-flowline-1")
    lake = WaterFeature.objects.get(source_id="nhd-waterbody-1")

    # Each keeps its own shape -- a generic column does not force a Multi container.
    assert stream.geom.geom_type == "LineString"
    assert lake.geom.geom_type == "Polygon"

    # Both reprojected out of NAD83 into the storage CRS.
    assert stream.geom.srid == 4326
    assert lake.geom.srid == 4326
    assert stream.geom.coords[0][0] == pytest.approx(-74.05, abs=1e-6)
    assert lake.geom.extent == pytest.approx(waterbody.extent, abs=1e-6)
