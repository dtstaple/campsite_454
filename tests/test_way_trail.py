"""
Trail details for a clicked trail way (TM05-97): a route member opens its route, a named
way outside any route opens a trail assembled from the connected same-name ways, and an
unnamed way has no trail (the map keeps its popup).

Ways are straight east-west lines in EPSG:5070 metres, chained through shared OSM node
ids or left a few metres apart, so which ways connect is exact.
"""

import pytest
from django.contrib.gis.geos import LineString, MultiLineString
from rest_framework.test import APIClient

from analysis.analyses import elevation
from geodata.assembly import ENDPOINT_JOIN_M, connected_same_name
from geodata.models import METRIC_SRID, Trail, TrailRoute

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

X0, Y0 = 1_770_000.0, 2_550_000.0
CALLS = []


@pytest.fixture(autouse=True)
def flat_3dep(monkeypatch):
    CALLS.clear()

    def post(points):
        CALLS.append(len(points))
        return {
            "samples": [
                {"locationId": i, "value": "500", "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        }

    monkeypatch.setattr(elevation, "post_samples", post)


def way(number, x0, x1, name="Adirondack Rail Trail", nodes=None, y=0.0):
    line = LineString((X0 + x0, Y0 + y), (X0 + x1, Y0 + y), srid=METRIC_SRID)
    return Trail.objects.create(
        source=Trail.Source.OSM,
        source_id=f"way/{number}",
        name=name,
        geom=MultiLineString(line.transform(4326, clone=True), srid=4326),
        length_m=abs(x1 - x0),
        osm_node_ids=nodes or [number * 10, number * 10 + 1],
    )


def trail_for(source_id):
    return APIClient().get(f"/api/trails/{source_id}/trail/")


def test_a_route_member_opens_its_route():
    member = way(1, 0, 1000, name="Van Hoevenberg Trail")
    TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/6619234",
        osm_id=6619234,
        name="Van Hoevenberg Trail",
        geom=member.geom,
        length_m=1000,
        member_way_ids=[1],
    )
    body = trail_for("way/1").json()
    assert body["osm_id"] == 6619234
    assert body["assembled"] is False
    assert body["assembly"] is None


def test_a_named_non_route_way_assembles_the_connected_same_name_ways():
    way(1, 0, 1000, nodes=[1, 2])
    way(2, 1000, 2000, nodes=[2, 3])  # shares node 2
    way(3, 2000 + ENDPOINT_JOIN_M - 5, 3000, nodes=[30, 31])  # 10 m gap, no shared node
    body = trail_for("way/2").json()
    assert body["assembled"] is True
    assert body["osm_id"] is None
    assert body["assembly"]["ways"] == 3
    assert body["assembly"]["note"] == "Assembled from mapped segments"
    assert body["name"] == "Adirondack Rail Trail"
    assert body["length_m"] == pytest.approx(3000 - (ENDPOINT_JOIN_M - 5), abs=1)
    assert body["profile"]["status"] == "ok"
    assert body["difficulty"]["label"] in {"Easy", "Moderate", "Hard"}


def test_assembly_stops_at_other_names_and_real_gaps():
    way(1, 0, 1000, nodes=[1, 2])
    way(2, 1000, 2000, name="Another Trail", nodes=[2, 3])  # connected, different name
    way(3, 2000, 3000, nodes=[3, 4])  # same name, only reachable through "Another Trail"
    way(4, 1000 + 200, 1500, y=500, nodes=[40, 41])  # same name, 200 m+ away
    members = connected_same_name(Trail.objects.get(source_id="way/1"))
    assert [m.source_id for m in members] == ["way/1"]


def test_any_member_gives_the_same_trail_and_reuses_the_cached_profile():
    way(1, 0, 1000, nodes=[1, 2])
    way(2, 1000, 2000, nodes=[2, 3])
    first = trail_for("way/1").json()
    calls_after_first = len(CALLS)
    second = trail_for("way/2").json()
    assert first["source_id"] == second["source_id"] == "assembled/way/1"
    assert second["line"] == first["line"]
    assert second["profile"]["source"]["cached"] is True
    assert len(CALLS) == calls_after_first  # no new 3DEP request


def test_an_unnamed_way_has_no_trail():
    way(1, 0, 1000, name="")
    response = trail_for("way/1")
    assert response.status_code == 404


def test_an_unknown_way_is_404():
    assert trail_for("way/999").status_code == 404
