"""
Invalid source geometry is repaired with ST_MakeValid in the shared load step (TM05-57).

PAD-US ships polygons with self-intersecting rings and nested shells; the framework used
to skip them, which silently dropped the High Peaks Wilderness. These tests use the two
shapes from the PAD-US run notes plus the GeometryCollection case: a repair that returns
a polygon *and* a stray line, from which only the polygon may be kept.
"""

import pytest
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point, Polygon

from geodata.models import IngestRun, PublicLand, WaterFeature
from pipeline.adapters import SourceAdapter
from pipeline.aoi import AreaOfInterest

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

ADK = AreaOfInterest(
    name="adirondacks", label="Adirondack Park", bbox=(-75.4, 43.0, -73.3, 44.9), states=("NY",)
)

BOWTIE = Polygon(
    ((-75.0, 43.0), (-74.0, 44.0), (-74.0, 43.0), (-75.0, 44.0), (-75.0, 43.0)), srid=4326
)
NESTED_SHELLS = MultiPolygon(
    Polygon(((-75.0, 43.0), (-74.0, 43.0), (-74.0, 44.0), (-75.0, 44.0), (-75.0, 43.0))),
    Polygon(((-74.8, 43.2), (-74.2, 43.2), (-74.2, 43.8), (-74.8, 43.8), (-74.8, 43.2))),
    srid=4326,
)
# A ring with a spike out and back along the same line: ST_MakeValid returns
# GEOMETRYCOLLECTION(POLYGON(...), LINESTRING(spike)).
SPIKE = GEOSGeometry(
    "SRID=4326;POLYGON((-74 44,-73.9 44,-73.9 44.1,-73.95 44.1,-73.95 44.15,"
    "-73.95 44.1,-74 44.1,-74 44))"
)


def run_with(model, records, clean_registry):
    class Adapter(SourceAdapter):
        name = "repair-test"
        source = model.Source.PADUS if model is PublicLand else model.Source.NHD

        def fetch(self, aoi):
            return [None]

        def normalize(self, raw):
            return records

    Adapter.model = model
    clean_registry.register(Adapter)
    return Adapter().run(ADK)


def test_inputs_really_are_invalid():
    assert not BOWTIE.valid and "Self-intersection" in BOWTIE.valid_reason
    assert not NESTED_SHELLS.valid and "Nested shells" in NESTED_SHELLS.valid_reason
    assert not SPIKE.valid


def test_self_intersecting_ring_is_repaired_and_loaded(clean_registry):
    run = run_with(PublicLand, [{"source_id": "bowtie", "geom": BOWTIE.clone()}], clean_registry)

    assert run.status == IngestRun.Status.SUCCESS
    assert run.record_count == 1
    parcel = PublicLand.objects.get(source_id="bowtie")
    assert parcel.geom.valid
    assert parcel.geom.geom_type == "MultiPolygon"
    # Both lobes of the bowtie survive: half of the 1x1 degree square.
    assert parcel.geom.area == pytest.approx(0.5)
    assert "Repaired with ST_MakeValid 1 record(s)" in run.notes
    assert "bowtie: Self-intersection" in run.notes


def test_nested_shells_are_repaired_into_a_polygon_with_a_hole(clean_registry):
    run_with(PublicLand, [{"source_id": "nested", "geom": NESTED_SHELLS.clone()}], clean_registry)
    parcel = PublicLand.objects.get(source_id="nested")
    assert parcel.geom.valid
    assert parcel.geom.area == pytest.approx(1.0 - 0.36)
    assert not parcel.geom.contains(Point(-74.5, 43.5, srid=4326))


def test_a_collection_after_repair_keeps_only_the_target_type(clean_registry):
    run_with(PublicLand, [{"source_id": "spike", "geom": SPIKE.clone()}], clean_registry)
    parcel = PublicLand.objects.get(source_id="spike")
    assert parcel.geom.geom_type == "MultiPolygon"
    assert parcel.geom.valid
    assert parcel.geom.area == pytest.approx(0.1 * 0.1)


def test_any_geometry_column_keeps_the_highest_dimension_of_a_collection(clean_registry):
    """WaterFeature.geom accepts any type, so a repaired collection keeps its polygons."""
    run_with(
        WaterFeature,
        [{"source_id": "spiky-lake", "geom": SPIKE.clone(), "feature_type": "lake"}],
        clean_registry,
    )
    lake = WaterFeature.objects.get(source_id="spiky-lake")
    assert lake.geom.geom_type == "MultiPolygon"
    assert lake.geom.valid


def test_a_rerun_of_repaired_geometry_is_idempotent(clean_registry):
    records = [{"source_id": "bowtie", "geom": BOWTIE.clone()}]
    run_with(PublicLand, records, clean_registry)
    clean_registry.unregister("repair-test")
    run_with(PublicLand, [{"source_id": "bowtie", "geom": BOWTIE.clone()}], clean_registry)
    assert PublicLand.objects.filter(source_id="bowtie").count() == 1
