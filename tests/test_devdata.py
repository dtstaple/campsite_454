"""
Tests for the portable dev-data tooling: the committed sample fixture and the seed,
reset_db, and build_sample management commands.

Everything runs against the real PostGIS test database. reset_db issues DDL, so its tests
use transactional_db rather than the default rollback-per-test wrapper.
"""

import json

import pytest
from django.contrib.gis.geos import GEOSGeometry, LineString, MultiPolygon, Point, Polygon
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from devdata.sample import (
    FEATURE_MODELS,
    FIXTURE_PATH,
    MAX_FIXTURE_BYTES,
    SAMPLE_AOI,
    clip,
    dump_sample,
    empty_layers,
    feature_count,
)
from geodata.models import IngestRun, PublicLand, Trail, WaterFeature


def _fixture_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in json.loads(FIXTURE_PATH.read_text(encoding="utf-8")):
        counts[entry["model"]] = counts.get(entry["model"], 0) + 1
    return counts


def _db_counts() -> dict[str, int]:
    return {m._meta.label_lower: m.objects.count() for m in FEATURE_MODELS}


def _make_run() -> IngestRun:
    return IngestRun.objects.create(source="osm", region="test", started_at=timezone.now())


# --- the committed fixture -------------------------------------------------------------


@pytest.mark.unit
def test_fixture_is_small():
    assert FIXTURE_PATH.stat().st_size < MAX_FIXTURE_BYTES


@pytest.mark.unit
def test_fixture_geometries_are_4326_and_inside_sample_box():
    box = SAMPLE_AOI.as_polygon()
    entries = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    geoms = [GEOSGeometry(e["fields"]["geom"]) for e in entries if "geom" in e["fields"]]

    assert geoms, "fixture has no features"
    for geom in geoms:
        assert geom.srid == 4326
        # covers rather than contains: clipped features legitimately touch the edge.
        assert box.buffer(1e-6).covers(geom)


@pytest.mark.unit
def test_fixture_has_every_layer():
    # Every layer, not "most": a sample with no campsites seeds cleanly and then shows a
    # map indistinguishable from a broken one.
    counts = _fixture_counts()
    missing = empty_layers(counts)
    assert not missing, (
        f"Committed sample has no rows for {', '.join(missing)} ({counts}). "
        "Rebuild it with `python manage.py build_sample` against a scratch database."
    )


@pytest.mark.unit
def test_empty_layers_names_each_missing_layer():
    counts = {"geodata.publicland": 3, "geodata.trail": 5, "geodata.waterfeature": 0}
    assert empty_layers(counts) == ["geodata.waterfeature", "geodata.campsite"]


# --- seed ------------------------------------------------------------------------------


@pytest.mark.django_db
def test_seed_loads_fixture_into_empty_database():
    call_command("seed")

    expected = _fixture_counts()
    for label, n in _db_counts().items():
        assert n == expected.get(label, 0), label


@pytest.mark.django_db
def test_seed_refuses_when_features_exist():
    Trail.objects.create(
        source="osm",
        source_id="way/1",
        geom=LineString((0, 0), (1, 1), srid=4326).union(LineString((2, 2), (3, 3), srid=4326)),
    )

    with pytest.raises(CommandError, match="already contains 1 feature"):
        call_command("seed")
    assert feature_count() == 1


# --- reset_db --------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_reset_db_drops_existing_rows_and_reseeds():
    run = _make_run()
    WaterFeature.objects.create(
        source="nhd", source_id="not-in-sample", geom=Point(-100, 40, srid=4326), last_run=run
    )

    call_command("reset_db", interactive=False, force=True)

    assert not WaterFeature.objects.filter(source_id="not-in-sample").exists()
    expected = _fixture_counts()
    for label, n in _db_counts().items():
        assert n == expected.get(label, 0), label


@pytest.mark.django_db(transaction=True)
def test_reset_db_keeps_postgis_and_its_tables():
    from django.db import connection

    call_command("reset_db", interactive=False, force=True)

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_extension WHERE extname = 'postgis'")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT count(*) FROM spatial_ref_sys WHERE srid = 4326")
        assert cursor.fetchone()[0] == 1


@pytest.mark.django_db
def test_reset_db_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG is False"):
        call_command("reset_db", interactive=False)


@pytest.mark.django_db
def test_reset_db_cancels_unless_confirmed(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    Trail.objects.create(
        source="osm",
        source_id="way/keep",
        geom=LineString((0, 0), (1, 1), srid=4326).union(LineString((2, 2), (3, 3), srid=4326)),
    )

    with pytest.raises(CommandError, match="cancelled"):
        call_command("reset_db")
    assert Trail.objects.filter(source_id="way/keep").exists()


# --- clipping and dumping --------------------------------------------------------------

BOX = Polygon.from_bbox((0, 0, 10, 10))
BOX.srid = 4326


@pytest.mark.unit
def test_clip_trims_line_to_box():
    line = LineString((-5, 5), (5, 5), srid=4326).union(LineString((20, 20), (30, 30), srid=4326))
    clipped = clip(line, "MULTILINESTRING", BOX)
    assert clipped.geom_type == "MultiLineString"
    assert clipped.extent == (0, 5, 5, 5)


@pytest.mark.unit
def test_clip_drops_lower_dimension_slivers():
    # Shares only a corner with the box: intersection is a point, which a polygon column
    # cannot hold.
    corner = MultiPolygon(Polygon.from_bbox((10, 10, 20, 20)), srid=4326)
    assert clip(corner, "MULTIPOLYGON", BOX) is None


@pytest.mark.unit
def test_clip_returns_none_outside_box():
    assert clip(Point(50, 50, srid=4326), "POINT", BOX) is None
    assert clip(Point(5, 5, srid=4326), "POINT", BOX).coords == (5, 5)


@pytest.mark.unit
def test_clip_passes_any_geometry_for_generic_column():
    poly = Polygon.from_bbox((5, 5, 15, 15))
    poly.srid = 4326
    assert clip(poly, "GEOMETRY", BOX).extent == (5, 5, 10, 10)


@pytest.mark.django_db
def test_dump_sample_round_trips_through_seed(tmp_path, monkeypatch):
    run = _make_run()
    inside = MultiPolygon(Polygon.from_bbox(SAMPLE_AOI.bbox), srid=4326)
    PublicLand.objects.create(source="padus", source_id="in", geom=inside, last_run=run)
    PublicLand.objects.create(
        source="padus",
        source_id="out",
        geom=MultiPolygon(Polygon.from_bbox((0, 0, 1, 1)), srid=4326),
        last_run=run,
    )
    path = tmp_path / "sample.json"

    counts = dump_sample(path)

    assert counts["geodata.publicland"] == 1
    assert counts["geodata.ingestrun"] == 1
    PublicLand.objects.all().delete()
    IngestRun.objects.all().delete()
    monkeypatch.setattr("devdata.management.commands.seed.FIXTURE_PATH", path)
    call_command("seed")
    assert list(PublicLand.objects.values_list("source_id", flat=True)) == ["in"]


# --- build_sample (network replaced by a stub adapter) ----------------------------------

BUILD_SAMPLE = "devdata.management.commands.build_sample"

EVERY_LAYER = {
    "geodata.ingestrun": 1,
    "geodata.publicland": 1,
    "geodata.trail": 1,
    "geodata.waterfeature": 1,
    "geodata.campsite": 1,
}


def _stub_build(monkeypatch, tmp_path, *, counts=EVERY_LAYER, size=10):
    """Replace the network and the dump. Returns (adapter names run, fixture path)."""
    ran = []

    class StubAdapter:
        def __init__(self, name):
            self.name = name

        def run(self, aoi):
            ran.append((self.name, aoi.name))
            return IngestRun.objects.create(
                source="osm", region=aoi.name, started_at=timezone.now(), record_count=0
            )

    def fake_dump(path):
        path.write_text("x" * size)
        return dict(counts)

    fixture = tmp_path / "sample.json"
    fixture.write_text("[]")
    monkeypatch.setattr(f"{BUILD_SAMPLE}.get_adapter", lambda name: lambda: StubAdapter(name))
    monkeypatch.setattr(f"{BUILD_SAMPLE}.dump_sample", fake_dump)
    monkeypatch.setattr(f"{BUILD_SAMPLE}.FIXTURE_PATH", fixture)
    return ran, fixture


@pytest.mark.django_db
def test_build_sample_runs_adapters_then_dumps(monkeypatch, tmp_path, capsys):
    ran, fixture = _stub_build(monkeypatch, tmp_path)
    monkeypatch.setenv("RIDB_API_KEY", "")

    call_command("build_sample")

    assert [name for name, _ in ran] == [
        "padus",
        "osm-trails",
        "osm-campsites",
        "nhd-flowlines",
        "nhd-waterbodies",
    ]
    assert {region for _, region in ran} == {SAMPLE_AOI.name}
    assert fixture.read_text() == "x" * 10
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.django_db
def test_build_sample_includes_ridb_when_key_set(monkeypatch, tmp_path):
    ran, _ = _stub_build(monkeypatch, tmp_path)
    monkeypatch.setenv("RIDB_API_KEY", "test-key")

    call_command("build_sample")

    assert ran[-1][0] == "ridb"


@pytest.mark.django_db
def test_build_sample_fails_and_keeps_fixture_when_a_layer_is_empty(monkeypatch, tmp_path):
    no_campsites = {**EVERY_LAYER, "geodata.campsite": 0}
    _, fixture = _stub_build(monkeypatch, tmp_path, counts=no_campsites)

    with pytest.raises(CommandError, match="no rows for geodata.campsite"):
        call_command("build_sample")

    assert fixture.read_text() == "[]"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.django_db
def test_build_sample_fails_and_keeps_fixture_when_too_large(monkeypatch, tmp_path):
    _, fixture = _stub_build(monkeypatch, tmp_path, size=MAX_FIXTURE_BYTES + 1)

    with pytest.raises(CommandError, match="budget"):
        call_command("build_sample")

    assert fixture.read_text() == "[]"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.django_db
def test_build_sample_refuses_non_empty_database():
    WaterFeature.objects.create(source="nhd", source_id="x", geom=Point(0, 0, srid=4326))
    with pytest.raises(CommandError, match="empty database"):
        call_command("build_sample")
