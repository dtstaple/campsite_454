"""
Trail difficulty and route type (TM05-82). Difficulty is checked against the formula for
each band; route type against routes built in EPSG:5070 metres, with other trails and
ponds placed at known distances from their ends.
"""

import math

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Polygon

from geodata.models import METRIC_SRID, Trail, TrailRoute, WaterFeature
from geodata.route_rating import (
    LOOP,
    OUT_AND_BACK,
    POINT_TO_POINT,
    config,
    difficulty,
    route_type,
    shenandoah_rating,
)

M_PER_MI, FT_PER_M = 1609.344, 3.28084
X0, Y0 = 1_770_000.0, 2_550_000.0


def miles(n):
    return n * M_PER_MI


def feet(n):
    return n / FT_PER_M


# --- difficulty -----------------------------------------------------------------------


def test_the_rating_is_shenandoahs_formula():
    # 5 mi and 1,000 ft: sqrt(1000 x 2 x 5) = 100.
    assert shenandoah_rating(miles(5), feet(1000)) == pytest.approx(100, abs=0.01)


@pytest.mark.parametrize(
    ("length_mi", "gain_ft", "label"),
    [
        (3, 200, "Easy"),  # 34.6
        (1, 1249, "Easy"),  # 49.98, just under 50
        (5, 1000, "Moderate"),  # 100
        (4, 2800, "Moderate"),  # 149.7, just under 150
        (7.7, 3200, "Hard"),  # 222: Van Hoevenberg to Marcy
    ],
)
def test_each_band(length_mi, gain_ft, label):
    assert difficulty(miles(length_mi), feet(gain_ft))["label"] == label


def test_the_bands_come_from_config():
    bands = [band["below"] for band in config()["difficulty"]["bands"]]
    assert bands == [50, 150, None]


def test_a_route_mapped_downhill_is_rated_by_its_climb_the_other_way():
    uphill = difficulty(miles(7), feet(2000), loss_m=0)
    downhill = difficulty(miles(7), gain_m=0, loss_m=feet(2000))
    assert downhill["label"] == uphill["label"] == "Hard"
    assert downhill["climb_m"] == pytest.approx(feet(2000), abs=0.1)


# --- route type -----------------------------------------------------------------------


def line(*points):
    return LineString([(X0 + x, Y0 + y) for x, y in points], srid=METRIC_SRID)


def make_route(line_m, member_ids=(1,)):
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/1",
        osm_id=1,
        name="Test Trail",
        geom=MultiLineString(line_m.transform(4326, clone=True), srid=4326),
        length_m=line_m.length,
        member_way_ids=list(member_ids),
    )


def other_trail_at(x, y, source_id="way/999"):
    """A short trail crossing the point (x, y), not one of the route's own ways."""
    geom = line((x - 20, y - 20), (x + 20, y + 20)).transform(4326, clone=True)
    return Trail.objects.create(
        source=Trail.Source.OSM,
        source_id=source_id,
        name="Other Trail",
        geom=MultiLineString(geom, srid=4326),
    )


def pond_at(x, y):
    ring = Polygon(
        [(X0 + x + dx, Y0 + y + dy) for dx, dy in ((0, 0), (40, 0), (40, 40), (0, 40), (0, 0))],
        srid=METRIC_SRID,
    ).transform(4326, clone=True)
    return WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id=f"pond-{x}-{y}",
        name="Test Pond",
        geom=MultiPolygon(ring, srid=4326),
        feature_type="lake",
    )


STRAIGHT = ((0, 0), (5000, 0))


@pytest.mark.django_db
@pytest.mark.integration
class TestRouteType:
    def test_ends_within_the_gap_are_a_measured_loop(self):
        loop = line((0, 0), (2000, 0), (2000, 2000), (0, 150))
        result = route_type(make_route(loop), loop)
        assert result["type"] == LOOP
        assert result["estimated"] is False

    def test_a_route_climbing_to_a_summit_is_out_and_back(self):
        straight = line(*STRAIGHT)
        other_trail_at(0, 0)
        elevations = [500 + 100 * i for i in range(10)]  # climbs 900 m to its far end
        result = route_type(make_route(straight), straight, elevations)
        assert result["type"] == OUT_AND_BACK
        assert result["estimated"] is True
        assert result["basis"]["end"] == "summit"

    def test_a_flat_route_has_no_summit(self):
        straight = line(*STRAIGHT)
        other_trail_at(0, 0)
        other_trail_at(5000, 0, "way/998")
        flat = [500.0] * 10
        assert route_type(make_route(straight), straight, flat)["type"] == POINT_TO_POINT

    def test_a_route_ending_at_a_pond_is_out_and_back(self):
        straight = line(*STRAIGHT)
        other_trail_at(0, 0)
        pond_at(5030, 0)
        result = route_type(make_route(straight), straight)
        assert result["type"] == OUT_AND_BACK
        assert result["basis"]["end"] == "pond"

    def test_a_route_to_a_dead_end_is_out_and_back(self):
        straight = line(*STRAIGHT)
        other_trail_at(0, 0)
        result = route_type(make_route(straight), straight)
        assert result["type"] == OUT_AND_BACK
        assert (result["basis"]["start"], result["basis"]["end"]) == ("connects", "dead_end")

    def test_both_ends_meeting_other_trails_is_point_to_point(self):
        straight = line(*STRAIGHT)
        other_trail_at(0, 0)
        other_trail_at(5000, 0, "way/998")
        pond_at(5030, 0)  # a junction at a lake is still a junction
        result = route_type(make_route(straight), straight)
        assert result["type"] == POINT_TO_POINT
        assert result["estimated"] is True

    def test_the_routes_own_ways_do_not_count_as_other_trails(self):
        straight = line(*STRAIGHT)
        other_trail_at(0, 0, "way/1")
        other_trail_at(5000, 0, "way/2")
        result = route_type(make_route(straight, member_ids=(1, 2)), straight)
        assert (result["basis"]["start"], result["basis"]["end"]) == ("dead_end", "dead_end")
        # Both ends likely reach roads, which are not mapped.
        assert result["type"] == POINT_TO_POINT


@pytest.mark.django_db
@pytest.mark.integration
def test_the_route_api_serves_difficulty_and_route_type(monkeypatch):
    from rest_framework.test import APIClient

    from analysis.analyses import elevation

    def climbing_3dep(points):
        return {
            "samples": [
                {"locationId": i, "value": str(500 + i * 2), "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        }

    monkeypatch.setattr(elevation, "post_samples", climbing_3dep)
    straight = line(*STRAIGHT)
    make_route(straight)
    body = APIClient().get("/api/routes/1/").json()

    assert body["difficulty"]["label"] in {"Easy", "Moderate", "Hard"}
    rated = body["difficulty"]
    expected = math.sqrt(rated["climb_m"] * FT_PER_M * 2 * rated["length_m"] / M_PER_MI)
    assert rated["shenandoah"] == pytest.approx(expected, abs=0.1)
    assert body["route_type"]["type"] in {LOOP, OUT_AND_BACK, POINT_TO_POINT}
    assert set(body["route_type"]) == {"type", "label", "estimated", "basis"}
