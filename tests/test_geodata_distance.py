"""
Tests for metre-correct distance queries (TM05-42).

The promise under test: `geom_m` is generated from `geom` in EPSG:5070 and stays in step
with it, and geodata.distance answers in metres -- not degrees -- for both nearest and
within-radius queries. Expected distances are geodesic values computed independently by
PostGIS on `geom::geography`, so the tests check the projection against ground truth
rather than against itself.

Index use is not asserted here: on a table of a handful of rows the planner correctly
prefers a sequential scan. It is checked with EXPLAIN ANALYZE against the full dataset by
`manage.py bench_distance`, recorded in docs/architecture.md.
"""

import pytest
from django.contrib.gis.geos import GEOSGeometry, LineString, MultiLineString, Point
from django.db import connection

from geodata.distance import nearest, nearest_distance_m, within
from geodata.models import METRIC_SRID, Campsite, Trail, WaterFeature
from pipeline.adapters.base import SourceAdapter

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

# Johns Brook valley, Adirondacks.
SITE = (-73.85, 44.18)


def make_water(source_id, geom, perennial=True):
    return WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id=source_id,
        geom=geom,
        feature_type=WaterFeature.FeatureType.STREAM,
        perennial=perennial,
    )


def geodesic_m(a: Point, b) -> float:
    """Ground truth: PostGIS spheroidal distance between two 4326 geometries."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ST_Distance(%s::geometry::geography, %s::geometry::geography)",
            [a.ewkt, b.ewkt],
        )
        return cursor.fetchone()[0]


def db_metric(geom) -> GEOSGeometry:
    """`geom` projected to METRIC_SRID by PostGIS, the same path `geom_m` takes."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT ST_AsEWKT(ST_Transform(%s::geometry, %s))", [geom.ewkt, METRIC_SRID])
        return GEOSGeometry(cursor.fetchone()[0])


def north_of(lon, lat, metres):
    """A point roughly `metres` due north; one degree of latitude is ~111.1 km."""
    return Point(lon, lat + metres / 111_120, srid=4326)


def test_geom_m_is_generated_in_metric_srid():
    water = make_water("w1", north_of(*SITE, 100))
    water.refresh_from_db()

    assert water.geom_m.srid == METRIC_SRID
    assert water.geom_m.distance(db_metric(water.geom)) < 0.001


def test_geom_m_follows_geom_when_it_changes():
    water = make_water("w1", north_of(*SITE, 100))
    water.geom = north_of(*SITE, 900)
    water.save()
    water.refresh_from_db()

    assert water.geom_m.distance(db_metric(water.geom)) < 0.001


def test_nearest_returns_metres_matching_geodesic():
    origin = Point(*SITE, srid=4326)
    near = make_water("near", north_of(*SITE, 60))
    make_water("far", north_of(*SITE, 400))

    feature = nearest(WaterFeature.objects.all(), *SITE)

    assert feature.pk == near.pk
    truth = geodesic_m(origin, near.geom)
    # Degrees would come back as ~0.0005; metres as ~60.
    assert truth == pytest.approx(60, rel=0.02)
    assert feature.distance_m == pytest.approx(truth, rel=0.01)


def test_nearest_orders_by_metres_not_degrees():
    """East-west degrees are shorter than north-south ones at 44N (~80 km vs ~111 km),
    so a degree-based ranking would pick the wrong feature here."""
    lon, lat = SITE
    # 0.001 deg north is ~111 m; 0.0012 deg east is ~96 m. Nearer in metres, farther in
    # degrees.
    make_water("north", Point(lon, lat + 0.001, srid=4326))
    east = make_water("east", Point(lon + 0.0012, lat, srid=4326))

    assert nearest(WaterFeature.objects.all(), lon, lat).pk == east.pk


def test_nearest_honours_queryset_filters():
    make_water("intermittent", north_of(*SITE, 30), perennial=False)
    perennial = make_water("perennial", north_of(*SITE, 250))

    feature = nearest(WaterFeature.objects.filter(perennial=True), *SITE)

    assert feature.pk == perennial.pk
    assert feature.distance_m == pytest.approx(250, rel=0.02)


def test_nearest_measures_to_lines_not_vertices():
    lon, lat = SITE
    # A trail passing 50 m north of the site, with both vertices ~1 km away.
    north = lat + 50 / 111_120
    Trail.objects.create(
        source=Trail.Source.OSM,
        source_id="t1",
        geom=MultiLineString(LineString((lon - 0.013, north), (lon + 0.013, north)), srid=4326),
    )

    assert nearest_distance_m(Trail.objects.all(), lon, lat) == pytest.approx(50, rel=0.02)


def test_nearest_on_empty_queryset_is_none():
    assert nearest(WaterFeature.objects.all(), *SITE) is None
    assert nearest_distance_m(WaterFeature.objects.all(), *SITE) is None


def test_within_uses_a_metre_radius_and_orders_nearest_first():
    make_water("a", north_of(*SITE, 300))
    make_water("b", north_of(*SITE, 100))
    make_water("outside", north_of(*SITE, 700))

    found = list(within(WaterFeature.objects.all(), *SITE, 500))

    assert [w.source_id for w in found] == ["b", "a"]
    assert found[0].distance_m == pytest.approx(100, rel=0.02)


def test_campsite_and_trail_carry_geom_m():
    site = Campsite.objects.create(
        source=Campsite.Source.OSM, source_id="c1", geom=Point(*SITE, srid=4326)
    )
    site.refresh_from_db()
    assert site.geom_m.srid == METRIC_SRID


def test_upsert_never_writes_generated_columns():
    class WaterAdapter(SourceAdapter):
        name = "test-water-distance"
        model = WaterFeature
        source = WaterFeature.Source.NHD
        source_srid = 4326

        def fetch(self, aoi):
            return []

        def normalize(self, raw):
            return []

    assert "geom_m" not in WaterAdapter.upsert_update_fields()
    assert "geom" in WaterAdapter.upsert_update_fields()
