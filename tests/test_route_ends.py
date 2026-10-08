"""
Campsites past a route's ends (TM05-73): no "mile 0" for a site that is not on the trail.

The route is a straight 4 km east-west line in EPSG:5070 metres, so where each campsite's
nearest point falls, and how far off it is, are exact.
"""

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, Point
from rest_framework.test import APIClient

from analysis.analyses import elevation
from geodata.models import METRIC_SRID, Campsite, TrailRoute
from geodata.route_rating import config, position_along

X0, Y0 = 1_770_000.0, 2_550_000.0
LENGTH = 4000.0
SETTINGS = {"off_end_m": 100, "end_zone_m": 50}


# --- the rule ---------------------------------------------------------------------------


def test_the_thresholds_live_in_config():
    assert config()["along"] == {"off_end_m": 100, "end_zone_m": 50}


def test_a_mid_trail_site_keeps_its_mile_however_far_off():
    assert position_along(2000, LENGTH, 400, SETTINGS)["position"] == "along"


def test_a_site_past_the_start_is_near_the_trailhead():
    place = position_along(0, LENGTH, 760, SETTINGS)
    assert place == {"position": "near_start", "position_label": "near the trailhead"}


def test_a_site_past_the_end_is_near_the_trails_end():
    place = position_along(LENGTH, LENGTH, 300, SETTINGS)
    assert place == {"position": "near_end", "position_label": "near the trail's end"}


def test_a_site_whose_nearest_point_is_just_inside_the_end_zone_counts_as_past_the_end():
    # A curving first segment: the nearest point is 18 m along, not the vertex itself.
    assert position_along(18, LENGTH, 760, SETTINGS)["position"] == "near_start"


def test_a_site_at_an_end_but_within_the_threshold_keeps_its_mile():
    assert position_along(0, LENGTH, 60, SETTINGS)["position"] == "along"


def test_a_site_beyond_the_threshold_but_outside_the_end_zone_keeps_its_mile():
    assert position_along(120, LENGTH, 300, SETTINGS)["position"] == "along"


# --- the API ----------------------------------------------------------------------------


def at(x, y):
    return Point(X0 + x, Y0 + y, srid=METRIC_SRID).transform(4326, clone=True)


@pytest.mark.django_db
@pytest.mark.integration
def test_the_route_api_labels_sites_past_either_end(monkeypatch):
    monkeypatch.setattr(
        elevation,
        "post_samples",
        lambda points: {
            "samples": [
                {"locationId": i, "value": "500", "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        },
    )
    line = LineString((X0, Y0), (X0 + LENGTH, Y0), srid=METRIC_SRID).transform(4326, clone=True)
    TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/1",
        osm_id=1,
        name="Test Trail",
        geom=MultiLineString(line, srid=4326),
        length_m=LENGTH,
        member_way_ids=[1],
    )
    for source_id, x, y in [
        ("mid", 2000, 300),  # mid-trail, 300 m off
        ("before", -400, 0),  # 400 m before the start
        ("after", LENGTH + 250, 0),  # 250 m past the end
        ("close", -60, 0),  # 60 m before the start: within the threshold
    ]:
        Campsite.objects.create(source="osm", source_id=source_id, geom=at(x, y))

    items = APIClient().get("/api/routes/1/?campsites_within_m=1000").json()["campsites"]["items"]
    by_id = {item["id"]: item for item in items}

    assert by_id["mid"]["position"] == "along"
    assert by_id["before"]["position_label"] == "near the trailhead"
    assert by_id["after"]["position_label"] == "near the trail's end"
    assert by_id["close"]["position"] == "along"
    assert by_id["close"]["position_label"] is None
