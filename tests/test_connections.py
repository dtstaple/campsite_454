"""
Connecting trails at junctions (TM05-101): junctions are shared OSM nodes, listed in mile
order, identified as the route or assembled trail the panel would open.

The trail runs east along y = 0 in EPSG:5070, as one way per kilometre with its node ids
in vertex order, so every junction's mile is exact.
"""

import pytest
from django.contrib.gis.geos import LineString, MultiLineString
from rest_framework.test import APIClient

from analysis.analyses import elevation
from analysis.analyses.elevation import stitch
from geodata.junctions import connections
from geodata.models import METRIC_SRID, Trail, TrailRoute

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

X0, Y0 = 1_770_000.0, 2_550_000.0


@pytest.fixture(autouse=True)
def flat_3dep(monkeypatch):
    monkeypatch.setattr(
        elevation,
        "post_samples",
        lambda points: {
            "samples": [
                {"locationId": i, "value": "500", "resolution": 1} for i in range(len(points))
            ]
        },
    )


def way(number, coords, nodes, name):
    line = LineString([(X0 + x, Y0 + y) for x, y in coords], srid=METRIC_SRID)
    return Trail.objects.create(
        source=Trail.Source.OSM,
        source_id=f"way/{number}",
        name=name,
        geom=MultiLineString(line.transform(4326, clone=True), srid=4326),
        length_m=line.length,
        osm_node_ids=nodes,
    )


@pytest.fixture
def main_route():
    # Three 1 km ways; nodes 100.. at every 500 m, shared at the way ends.
    way(1, [(0, 0), (500, 0), (1000, 0)], [100, 101, 102], "Main Trail")
    way(2, [(1000, 0), (1500, 0), (2000, 0)], [102, 103, 104], "Main Trail")
    way(3, [(2000, 0), (2500, 0), (3000, 0)], [104, 105, 106], "Main Trail")
    geom = MultiLineString(
        [w.geom[0] for w in Trail.objects.filter(name="Main Trail").order_by("source_id")],
        srid=4326,
    )
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/1",
        osm_id=1,
        name="Main Trail",
        geom=geom,
        length_m=3000,
        member_way_ids=[1, 2, 3],
    )


def found(route):
    line_m, _ = stitch(route.geom)
    return connections(route, line_m)


def miles_of(entry):
    return [j["distance_along_m"] for j in entry["junctions"]]


def test_a_named_trail_sharing_a_node_is_a_connection_at_that_mile(main_route):
    way(10, [(1500, 0), (1500, 800)], [103, 900], "Pond Spur")  # meets at node 103, 1.5 km
    (entry,) = found(main_route)
    assert entry["name"] == "Pond Spur"
    assert entry["osm_id"] is None and entry["way_id"] == "way/10"
    assert miles_of(entry) == pytest.approx([1500], abs=0.5)
    assert entry["junctions"][0]["node_id"] == 103


def test_crossing_without_a_shared_node_is_not_a_junction(main_route):
    way(11, [(700, -300), (700, 300)], [910, 911], "Crossing Path")  # crosses, no shared node
    assert found(main_route) == []


def test_unnamed_and_same_name_ways_are_left_out(main_route):
    way(12, [(500, 0), (500, 400)], [101, 920], "")
    way(13, [(2500, 0), (2500, 400)], [105, 930], "main trail")  # same name, any case
    assert found(main_route) == []


def test_connections_are_in_mile_order(main_route):
    way(20, [(2500, 0), (2500, 600)], [105, 940], "Upper Spur")
    way(21, [(500, 0), (500, -600)], [101, 941], "Lower Spur")
    way(22, [(1500, 0), (1500, -600)], [103, 942], "Middle Spur")
    assert [e["name"] for e in found(main_route)] == ["Lower Spur", "Middle Spur", "Upper Spur"]


def test_a_trail_meeting_twice_lists_both_junctions_in_order(main_route):
    way(30, [(500, 0), (500, 500), (2500, 500), (2500, 0)], [101, 950, 951, 105], "Loop Path")
    (entry,) = found(main_route)
    assert miles_of(entry) == pytest.approx([500, 2500], abs=0.5)


def test_a_connecting_route_member_opens_its_route(main_route):
    spur = way(40, [(1000, 0), (1000, 900)], [102, 960], "Summit Trail")
    TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/2",
        osm_id=2,
        name="Summit Trail",
        geom=spur.geom,
        length_m=900,
        member_way_ids=[40],
    )
    (entry,) = found(main_route)
    assert (entry["name"], entry["osm_id"], entry["way_id"]) == ("Summit Trail", 2, None)
    assert miles_of(entry) == pytest.approx([1000], abs=0.5)


def test_the_route_detail_carries_its_connections(main_route):
    way(10, [(1500, 0), (1500, 800)], [103, 900], "Pond Spur")
    body = APIClient().get("/api/routes/1/").json()
    assert [c["name"] for c in body["connections"]] == ["Pond Spur"]
    junction = body["connections"][0]["junctions"][0]
    assert set(junction) == {"node_id", "lon", "lat", "distance_along_m"}
