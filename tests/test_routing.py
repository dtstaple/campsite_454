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
from geodata.models import METRIC_SRID, Campsite, Connector, Trail
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


def test_a_single_trail_route_snaps_to_the_nearest_point_on_a_segment(network):
    # TM05-137: (480, 10) projects onto the West Trail at x = 480, between its vertices at
    # 0 and 500, not onto the nearest vertex.
    planned = service.plan([lonlat(480, 10), lonlat(1000, 0)], "distance")
    way_token, end = (s.token for s in planned.stops)
    assert end == "102"
    # w<way>-<decimetres along it>: 480 m, to the metre geometry's precision.
    assert way_token.startswith("w1-") and int(way_token[3:]) == pytest.approx(4800, abs=5)
    assert planned.stops[0].node < 0  # a point between junctions, for this request
    assert planned.route.length_m == pytest.approx(520, abs=0.5)
    assert planned.trails == [
        {"name": "West Trail", "kind": "trail", "length_m": pytest.approx(520, abs=0.5)}
    ]
    assert planned.stops[0].snapped_m == pytest.approx(10, abs=0.5)
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


def test_an_unreachable_destination_names_where_a_connected_route_would_start(network):
    with pytest.raises(service.PlanningError) as caught:
        service.plan([lonlat(0, 0), lonlat(5000, 0)], "naismith")
    message = str(caught.value)
    assert "No connected trails or roads join West Trail and Island Trail" in message
    assert "The nearest place a connected route is possible is on" in message
    suggestion = caught.value.suggestion
    # The Island Trail's nearest node to the start is its west end, 5 km away; the West
    # network's nearest to the end is the Valley Trail's end, 3 km away: that one wins.
    assert suggestion["instead_of"] == "stop"
    assert suggestion["distance_m"] == pytest.approx(3000, abs=1)
    assert (suggestion["lon"], suggestion["lat"]) == pytest.approx(tuple(lonlat(2000, 0)), abs=1e-5)


def test_a_click_by_an_isolated_path_snaps_to_the_connected_network(network):
    # A few metres from the start, a path that joins nothing (paths round a lodge, say):
    # nearer the click than the West Trail, but routing from it could never reach the end.
    way(7, [(-20, 40), (20, 40)], [700, 701], "Lodge Path")
    build_region("adirondacks", fetch=ridge_height, workers=1, log=lambda *_: None)
    planned = service.plan([lonlat(0, 35), lonlat(1000, 1000)], "distance")
    assert planned.stops[0].token == "100"
    assert planned.stops[0].snapped_m == pytest.approx(35, abs=0.5)
    assert planned.trails[0]["name"] == "West Trail"


def test_a_click_far_from_any_trail_is_not_snapped(network):
    with pytest.raises(service.PlanningError, match="No mapped trail within 1000 m"):
        service.plan([lonlat(0, 0), lonlat(4000, 4000)])


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
    # The stop is stored to the decimetre, so the re-solved line matches to ~10 cm.
    assert again.trail_route.geom.equals_exact(planned.trail_route.geom, 1e-6)
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
    assert "No connected trails or roads join" in far.json()["error"]
    assert far.json()["suggestion"]["instead_of"] == "stop"
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


# --- TM05-137: forgiving snapping, bridged gaps and road walks ----------------------------


def connector(number, coords, nodes, name, highway="residential"):
    line = LineString([(X0 + x, Y0 + y) for x, y in coords], srid=METRIC_SRID)
    return Connector.objects.create(
        source=Connector.Source.OSM,
        source_id=f"way/{number}",
        name=name,
        highway=highway,
        geom=MultiLineString(line.transform(4326, clone=True), srid=4326),
        length_m=line.length,
        osm_node_ids=nodes,
    )


def rebuild():
    return build_region("adirondacks", fetch=ridge_height, workers=1, log=lambda *_: None)


def test_a_stop_partway_along_a_segment_resolves_to_the_same_point(network):
    planned = service.plan([lonlat(250, 20), lonlat(2000, 0)], "distance")
    token = planned.stops[0].token
    assert token.startswith("w1-") and int(token[3:]) == pytest.approx(2500, abs=5)
    assert planned.route.length_m == pytest.approx(1750, abs=0.5)
    again = service.resolve(planned.id)
    assert again.route.length_m == pytest.approx(1750, abs=0.5)
    assert (again.stops[0].lon, again.stops[0].lat) == pytest.approx(
        tuple(lonlat(250, 0)), abs=1e-5
    )


def test_a_click_prefers_the_connected_network_over_a_nearer_fragment(network):
    # A 60 m path 40 m from the click joins nothing; the Ridge Trail is 120 m away.
    way(7, [(1090, 470), (1150, 470)], [700, 701], "Lodge Path")
    rebuild()
    planned = service.plan([lonlat(1120, 430), lonlat(0, 0)], "distance")
    assert planned.stops[0].trail_name == "Ridge Trail"
    assert planned.stops[0].snapped_m == pytest.approx(120, abs=0.5)


def test_a_near_miss_gap_is_bridged(network):
    # The Spur Trail starts 8 m past the Valley Trail's end, with no shared node.
    way(8, [(2008, 0), (2500, 0)], [800, 801], "Spur Trail")
    build = rebuild()
    assert build.provenance["bridged_gaps"] == 1
    bridge = TrailEdge.objects.get(kind=TrailEdge.Kind.BRIDGE)
    assert {bridge.start_node, bridge.end_node} == {800, 302}
    assert bridge.length_m == pytest.approx(8, abs=0.1)
    planned = service.plan([lonlat(0, 0), lonlat(2500, 0)], "distance")
    kinds = {t["name"]: t["kind"] for t in planned.trails}
    assert kinds["Gap between mapped trails"] == "gap bridged"
    assert planned.off_trail["bridged_m"] == pytest.approx(8, abs=0.1)


def test_trails_that_cross_without_a_shared_node_are_joined_unless_one_passes_over(network):
    way(9, [(250, -300), (250, 300)], [910, 911], "Crossing Trail")
    overpass = way(10, [(750, -300), (750, 300)], [920, 921], "Footbridge Trail")
    overpass.raw = {"tags": {"bridge": "yes"}}
    overpass.save()
    build = rebuild()
    assert build.provenance["crossings_joined"] == 1
    planned = service.plan([lonlat(250, -300), lonlat(1000, 0)], "distance")
    assert planned.stops[0].trail_name == "Crossing Trail"
    assert planned.route.length_m == pytest.approx(300 + 750, abs=1)
    # The footbridge passes over the West Trail: never joined, so it stays one edge, and a
    # click on its end snaps to the West Trail 300 m away instead.
    assert TrailEdge.objects.filter(name="Footbridge Trail").count() == 1
    assert TrailEdge.objects.filter(name="Crossing Trail").count() == 2
    over = service.plan([lonlat(750, -300), lonlat(1000, 0)], "distance")
    assert over.stops[0].trail_name == "West Trail"


def test_a_road_walk_joins_two_trails_and_is_labelled_and_costed(network):
    way(11, [(2600, 0), (3000, 0)], [960, 961], "East Trail")
    connector(51, [(2000, 0), (2300, 0), (2600, 0)], [302, 955, 960], "Blue Ridge Road")
    # A road far from every trail is dropped: 3 km beyond the East Trail's end.
    connector(52, [(3000, 0), (3000, 3000)], [961, 990], "Far Road")
    build = rebuild()
    assert build.provenance["edge_kinds"]["road"] == 1
    road = TrailEdge.objects.get(kind=TrailEdge.Kind.ROAD)
    assert (road.name, road.cost_factor) == ("Blue Ridge Road", 1.5)
    planned = service.plan([lonlat(0, 0), lonlat(3000, 0)], "distance")
    assert {
        "name": "Blue Ridge Road",
        "kind": "road walk",
        "length_m": pytest.approx(600, abs=1),
    } in (planned.trails)
    assert planned.off_trail["road_walk_m"] == pytest.approx(600, abs=1)


def test_a_route_leaves_trail_only_when_the_road_saves_enough(network):
    way(11, [(2600, 0), (3000, 0)], [960, 961], "East Trail")
    connector(51, [(2000, 0), (2300, 0), (2600, 0)], [302, 955, 960], "Blue Ridge Road")
    # A trail beside the road, 608 m against the road's 600 m: 608 < 600 x 1.5.
    way(12, [(2000, 0), (2300, 50), (2600, 0)], [302, 970, 960], "Parallel Trail")
    rebuild()
    planned = service.plan([lonlat(0, 0), lonlat(3000, 0)], "distance")
    names = [t["name"] for t in planned.trails]
    assert "Parallel Trail" in names and "Blue Ridge Road" not in names
    assert planned.off_trail["road_walk_m"] == 0


def test_a_rebuild_reuses_the_previous_builds_elevation(network):
    calls = []

    def counting(points):
        calls.append(len(points))
        return ridge_height(points)

    build_region("adirondacks", fetch=counting, workers=1, log=lambda *_: None)
    assert calls == []  # every way was measured by the network fixture's build
    ridge = TrailEdge.objects.get(name="Ridge Trail")
    assert ridge.ascent_m == pytest.approx(300, abs=0.5)


def test_a_driveway_is_walked_only_where_it_meets_a_trail(network):
    way(11, [(2600, 0), (3000, 0)], [960, 961], "East Trail")
    # Hoffman Notch: road -> driveway -> trail. The driveway meets the East Trail at 960.
    connector(51, [(2000, 0), (2300, 0)], [302, 955], "Blue Ridge Road")
    lane = connector(53, [(2300, 0), (2600, 0)], [955, 960], "Branch Road", highway="service")
    lane.raw = {"tags": {"highway": "service", "service": "driveway"}}
    lane.save()
    # A driveway off the same road that meets no trail is left out.
    other = connector(54, [(2300, 0), (2300, 200)], [955, 956], "Somebody's Lane", "service")
    other.raw = {"tags": {"highway": "service", "service": "driveway"}}
    other.save()
    rebuild()
    assert TrailEdge.objects.filter(connector=lane).exists()
    assert not TrailEdge.objects.filter(connector=other).exists()
    planned = service.plan([lonlat(0, 0), lonlat(3000, 0)], "distance")
    assert planned.off_trail["road_walk_m"] == pytest.approx(600, abs=1)
