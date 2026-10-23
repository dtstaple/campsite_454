"""
Routes across connected trails (TM05-119): building the graph from shared OSM nodes,
snapping clicks, planning and re-solving routes, the API, and overnight plans on a
planned route.

The network, in EPSG:5070 metres from (X0, Y0), with elevation 0.3 x y (so the Ridge
Trail climbs 300 m):

    (0,1000)                 (1000,1000) 202 ----------------.
                                  |                           \\  Connector (way 4)
                             Ridge Trail (way 2)               \\
                                  |                             \\
    100 ---- 101 ---- 102 ---- (1000,0) ---- 301 ---- 302 (2000,0)
       West Trail (way 1)            Valley Trail (way 3)

    Island Trail (way 5): 900 -- 901 at x = 5000..5500, sharing no node.
"""

import pytest
from django.contrib.auth.models import User
from django.contrib.gis.geos import LineString, MultiLineString, Point
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from analysis.analyses import elevation
from geodata.models import METRIC_SRID, Campsite, Trail
from planning.models import TripPlan
from routing import service
from routing.build import build_region, cut_points, rise_and_fall, sample_distances
from routing.models import TrailEdge, TrailGraphBuild

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

X0, Y0 = 1_770_000.0, 2_550_000.0


def to_4326(x, y):
    return Point(X0 + x, Y0 + y, srid=METRIC_SRID).transform(4326, clone=True)


def lonlat(x, y):
    p = to_4326(x, y)
    return [p.x, p.y]


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


def ridge_height(points):
    """The build's 3DEP stand-in: elevation 0.3 m per metre north of Y0."""
    values = []
    for p in points:
        metric = Point(p.x, p.y, srid=4326).transform(METRIC_SRID, clone=True)
        values.append(round(0.3 * (metric.y - Y0), 3))
    return values, {"datasets": ["stub"]}


@pytest.fixture(autouse=True)
def flat_profile_3dep(monkeypatch):
    """The route profile's 3DEP (RouteProfile) is flat; only the graph build sees hills."""
    monkeypatch.setattr(
        elevation,
        "post_samples",
        lambda points: {
            "samples": [
                {"locationId": i, "value": "500", "resolution": 1} for i in range(len(points))
            ]
        },
    )
    service.forget_graphs()
    yield
    service.forget_graphs()


@pytest.fixture
def network():
    way(1, [(0, 0), (500, 0), (1000, 0)], [100, 101, 102], "West Trail")
    way(2, [(1000, 0), (1000, 500), (1000, 1000)], [102, 201, 202], "Ridge Trail")
    way(3, [(1000, 0), (1500, 0), (2000, 0)], [102, 301, 302], "Valley Trail")
    way(4, [(2000, 0), (1500, 500), (1000, 1000)], [302, 401, 202], "Connector")
    way(5, [(5000, 0), (5500, 0)], [900, 901], "Island Trail")
    return build_region("adirondacks", fetch=ridge_height, workers=1, log=lambda *_: None)


# --- building --------------------------------------------------------------------------


def test_ways_are_cut_at_shared_nodes_and_their_ends():
    assert cut_points([1, 2, 3, 4, 5], {3}) == [0, 2, 4]
    assert cut_points([1, 2, 3, 1], {1}) == [0, 3]  # a loop is cut at its shared start
    assert sample_distances(120, 50) == [0, 50, 100, 120]
    assert rise_and_fall([0, 5, 3, 10]) == (12, 2)


def test_the_graph_has_one_edge_per_stretch_between_junctions(network):
    assert (network.ways, network.edges, network.nodes, network.ways_skipped) == (5, 5, 6, 0)
    ridge = TrailEdge.objects.get(name="Ridge Trail")
    assert (ridge.start_node, ridge.end_node, ridge.node_ids) == (102, 202, [102, 201, 202])
    assert ridge.length_m == pytest.approx(1000, abs=0.5)
    assert ridge.ascent_m == pytest.approx(300, abs=0.5)
    assert ridge.descent_m == pytest.approx(0, abs=0.5)
    assert ridge.samples[0] == [0.0, pytest.approx(0, abs=0.5)]
    assert network.provenance["datasets"] == ["stub"]


def test_a_way_whose_node_ids_do_not_match_its_vertices_is_skipped(network):
    way(6, [(0, 3000), (500, 3000)], [1, 2, 3], "Broken Trail")
    rebuilt = build_region("adirondacks", fetch=ridge_height, workers=1, log=lambda *_: None)
    assert rebuilt.ways_skipped == 1
    assert not TrailEdge.objects.filter(name="Broken Trail").exists()


def test_a_rebuild_replaces_the_edges_and_the_cached_graph(network):
    first, _ = service.region_graph("adirondacks")
    rebuilt = build_region("adirondacks", fetch=ridge_height, workers=1, log=lambda *_: None)
    second, was_cached = service.region_graph("adirondacks")
    assert (first.build_id, second.build_id, was_cached) == (network.id, rebuilt.id, False)
    assert TrailEdge.objects.count() == 5
    assert TrailGraphBuild.objects.count() == 2


# --- planning ----------------------------------------------------------------------------


def test_a_single_trail_route_between_two_vertices(network):
    planned = service.plan([lonlat(480, 10), lonlat(1000, 0)], "distance")
    assert [s.node for s in planned.stops] == [101, 102]  # 101 is mid-edge: split there
    assert planned.route.length_m == pytest.approx(500, abs=0.5)
    assert planned.trails == [{"name": "West Trail", "length_m": pytest.approx(500, abs=0.5)}]
    assert planned.stops[0].snapped_m == pytest.approx(22.4, abs=0.5)
    assert planned.trail_route.member_way_ids == [1]
    assert planned.trail_route.osm_id is None
    assert planned.trail_route.source_id.startswith("planned/")


def test_a_multi_trail_route_names_every_trail_it_uses(network):
    planned = service.plan([lonlat(0, 0), lonlat(1000, 1000)], "distance")
    assert [t["name"] for t in planned.trails] == ["West Trail", "Ridge Trail"]
    assert planned.route.length_m == pytest.approx(2000, abs=1)
    assert planned.route.ascent_m == pytest.approx(300, abs=1)
    assert planned.trail_route.member_way_ids == [1, 2]
    line = planned.trail_route.geom_m[0]
    assert line.coords[0] == pytest.approx((X0, Y0), abs=0.5)
    assert line.coords[-1] == pytest.approx((X0 + 1000, Y0 + 1000), abs=0.5)


def test_waypoints_are_visited_in_order(network):
    planned = service.plan([lonlat(0, 0), lonlat(2000, 0), lonlat(1000, 1000)], "distance")
    assert [t["name"] for t in planned.trails] == ["West Trail", "Valley Trail", "Connector"]
    # One leg per pair of stops. Node 302 is on both the Valley Trail and the Connector,
    # so the legs are checked by length, not by the name a junction happens to snap to.
    assert [round(leg["length_m"]) for leg in planned.legs] == [2000, 1414]
    assert planned.id == "adirondacks:distance:100,302,202"


def test_naismith_and_distance_can_choose_different_trails(network):
    # Down from 202 to 100 both ways descend; up from 100 to 202 the Ridge (1 km, +300 m)
    # takes 12 + 30 = 42 min, the valley and connector (~2.7 km, +300 m) longer.
    assert service.plan([lonlat(0, 0), lonlat(1000, 1000)], "naismith").trails[1]["name"] == (
        "Ridge Trail"
    )


def test_an_unreachable_destination_says_the_trails_do_not_connect(network):
    with pytest.raises(service.PlanningError, match="No connected trails join these points"):
        service.plan([lonlat(0, 0), lonlat(5000, 0)], "naismith")


def test_a_click_by_an_isolated_path_snaps_to_the_connected_network(network):
    # A few metres from the start, a path that joins nothing (paths round a lodge, say):
    # nearer the click than the West Trail, but routing from it could never reach the end.
    way(7, [(-20, 40), (20, 40)], [700, 701], "Lodge Path")
    build_region("adirondacks", fetch=ridge_height, workers=1, log=lambda *_: None)
    planned = service.plan([lonlat(0, 35), lonlat(1000, 1000)], "distance")
    assert planned.stops[0].node == 100
    assert planned.stops[0].snapped_m == pytest.approx(35, abs=0.5)
    assert planned.trails[0]["name"] == "West Trail"


def test_a_click_far_from_any_trail_is_not_snapped(network):
    with pytest.raises(service.PlanningError, match="No mapped trail within 400 m"):
        service.plan([lonlat(0, 0), lonlat(3000, 3000)])


def test_bad_requests_are_planning_errors(network):
    with pytest.raises(service.PlanningError, match="up to 8 stops"):
        service.plan([lonlat(0, 0)])
    with pytest.raises(service.PlanningError, match="cost must be"):
        service.plan([lonlat(0, 0), lonlat(1000, 0)], "scenic")
    with pytest.raises(service.PlanningError, match="Not a planned route id"):
        service.resolve("adirondacks:naismith:")
    with pytest.raises(service.PlanningError, match="not on the adirondacks trail graph"):
        service.resolve("adirondacks:naismith:100,999999")


def test_a_route_id_resolves_to_the_same_route(network):
    planned = service.plan([lonlat(480, 10), lonlat(2000, 0), lonlat(1000, 1000)], "naismith")
    again = service.resolve(planned.id)
    assert again.trail_route.geom.equals_exact(planned.trail_route.geom, 1e-9)
    assert again.trails == planned.trails
    assert again.timing_ms["graph_was_cached"] is True


def test_two_stops_on_one_edge_split_it_twice(network):
    planned = service.plan([lonlat(1000, 0), lonlat(1000, 500), lonlat(1000, 1000)], "distance")
    assert planned.route.length_m == pytest.approx(1000, abs=0.5)
    edge = TrailEdge.objects.get(name="Connector")
    planned = service.plan([lonlat(2000, 0), lonlat(1500, 500)], "distance")
    assert planned.route.length_m == pytest.approx(edge.length_m / 2, abs=0.5)


# --- the API -----------------------------------------------------------------------------


def test_the_api_plans_a_route_and_serves_it_again_by_id(network):
    client = APIClient()
    body = {"points": [lonlat(0, 0), lonlat(1000, 1000)], "cost": "naismith"}
    planned = client.post("/api/routing/plan/", body, format="json")
    assert planned.status_code == 200, planned.content
    detail = planned.json()
    block = detail["planned"]
    assert block["id"] == "adirondacks:naismith:100,202"
    assert [t["name"] for t in block["trails"]] == ["West Trail", "Ridge Trail"]
    assert block["graph_totals"]["ascent_m"] == pytest.approx(300, abs=1)
    assert detail["profile"]["status"] == "ok"
    assert detail["line"]["length_m"] == pytest.approx(2000, abs=1)
    assert detail["osm_id"] is None and detail["name"].startswith("Route via")
    assert set(block["timing_ms"]) >= {"snap", "graph_load", "search", "assemble", "total"}

    again = client.get(f"/api/routing/{block['id']}/")
    assert again.status_code == 200
    assert again.json()["line"] == detail["line"]


def test_the_api_says_why_it_cannot_route(network):
    client = APIClient()
    far = client.post(
        "/api/routing/plan/", {"points": [lonlat(0, 0), lonlat(5000, 0)]}, format="json"
    )
    assert far.status_code == 422
    assert "No connected trails join these points" in far.json()["error"]
    assert client.get("/api/routing/adirondacks:naismith:100,999999/").status_code == 422
    assert client.get("/api/routing/not-an-id/").status_code == 404


def test_find_campsites_and_gpx_work_on_a_planned_route(network):
    client = APIClient()
    route_id = "adirondacks:distance:100,302,202"
    found = client.get(f"/api/routing/{route_id}/candidates/")
    assert found.status_code == 200
    assert found.json()["status"] in {"ok", "unavailable"}
    gpx = client.get(f"/api/routing/{route_id}/gpx/")
    assert gpx.status_code == 200
    assert gpx["Content-Type"].startswith("application/gpx+xml")
    assert b"<trk>" in gpx.content


# --- overnight plans on a planned route --------------------------------------------------


def client_for(username):
    user = User.objects.create_user(username=username, password="a-strong-passw0rd!")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
    return client


def campsite(source_id, x, y):
    return Campsite.objects.create(
        source=Campsite.Source.OSM, source_id=source_id, name=source_id, geom=to_4326(x, y)
    )


def test_nights_on_a_planned_route_work_like_a_trail(network):
    campsite("node/1", 1000, 30)  # by the junction, 1 km in
    campsite("node/2", 1950, 20)  # near the end of the Valley Trail, 2 km in
    client = client_for("alice")
    route_id = "adirondacks:distance:100,302,202"

    preview = client.post(
        "/api/plans/preview/",
        {"planned_route": route_id, "stop_ids": ["node/2", "node/1"]},
        format="json",
    )
    assert preview.status_code == 200, preview.content
    worked = preview.json()
    assert [s["id"] for s in worked["stops"]] == ["node/1", "node/2"]
    # 1,000 m to the first night, 950 m to the second, then the last of the Valley Trail
    # and the 1,414 m Connector.
    assert [round(d["distance_m"]) for d in worked["days"]] == [1000, 950, 1464]

    saved = client.post(
        "/api/plans/",
        {"planned_route": route_id, "stop_ids": ["node/1"], "name": "Valley loop"},
        format="json",
    )
    assert saved.status_code == 201, saved.content
    plan = TripPlan.objects.get()
    assert (plan.osm_id, plan.from_way, plan.planned_route) == (None, "", route_id)
    listed = client.get("/api/plans/", {"planned_route": route_id}).json()
    assert [p["planned_route"] for p in listed] == [route_id]
    assert client.get(f"/api/plans/{plan.id}/").json()["nights"] == 1
    gpx = client.get(f"/api/plans/{plan.id}/gpx/")
    assert gpx.status_code == 200 and b"Night 1" in gpx.content


def test_a_plan_on_a_route_that_no_longer_resolves_says_so(network):
    client = client_for("bob")
    response = client.post(
        "/api/plans/preview/",
        {"planned_route": "adirondacks:naismith:100,999999", "stop_ids": []},
        format="json",
    )
    assert response.status_code == 400
    assert "not on the adirondacks trail graph" in response.json()["error"]


def test_a_route_id_across_unconnected_trails_says_they_do_not_connect(network):
    with pytest.raises(service.PlanningError, match="don't connect West Trail to Island Trail"):
        service.resolve("adirondacks:distance:100,900")
