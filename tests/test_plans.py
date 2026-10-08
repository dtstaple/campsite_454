"""
Overnight plans along a trail (TM05-81): the day calculations, stop ordering and
rejection, saving/reopening/deleting, per-user isolation, legality warnings, and GPX.

The route is a straight 4 km line in EPSG:5070. 3DEP is stubbed with a tent-shaped
profile -- up 0.1 m per metre to a 700 m peak at 2 km, then down -- so each day's gain
and loss are known exactly.
"""

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xmlschema
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import LineString, MultiLineString, Point
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from analysis.analyses import elevation
from analysis.base import AnalysisError
from geodata.models import Campsite, Trail, TrailRoute
from planning.days import day_stats, smoothed_profile, value_at
from planning.models import TripPlan

User = get_user_model()
FIXTURES = Path(__file__).parent / "fixtures"
NS = {"g": "http://www.topografix.com/GPX/1/1"}
X0, Y0 = 1_770_000.0, 2_550_000.0
LENGTH = 4000
PARAMS = {"spacing_m": 25, "smoothing_window_m": 100, "threshold_m": 3, "grade_window_m": 100}


def tent(d):
    return 500 + 0.1 * min(d, LENGTH - d)


# --- days (pure) ---------------------------------------------------------------------------


def test_value_at_interpolates_and_clamps():
    assert value_at([0, 10, 20], [0, 5, 15], 15) == 10
    assert value_at([0, 10, 20], [0, 5, 15], -5) == 0
    assert value_at([0, 10, 20], [0, 5, 15], 99) == 15


def test_days_split_the_profile_at_the_stops():
    distances = [i * 25.0 for i in range(LENGTH // 25 + 1)]
    smoothed = smoothed_profile([tent(d) for d in distances], PARAMS)
    days = day_stats([0, 1000, 3000, LENGTH], distances, smoothed, PARAMS)

    assert [d["distance_m"] for d in days] == [1000, 2000, 1000]
    # The true figures are 100 m a leg. Measured the route's way they come out a few metres
    # under: smoothing lifts the route's first and last samples 2.5 m (the window shrinks
    # at the ends) and rounds the summit, and the 3 m threshold leaves under 3 m uncounted
    # at the end of a day -- the same rule, and so the same bias, as the route's own gain.
    assert [(d["gain_m"], d["loss_m"]) for d in days] == [(95, 0), (95, 95), (0, 95)]


def test_one_day_is_exactly_the_routes_own_gain_and_loss():
    """No stops in between: the same smoothing and threshold as the route's profile stats,
    so the trail panel and the plan agree. With stops, the days add up to within the
    threshold per stop (190 m here against the route's 194 m)."""
    distances = [i * 25.0 for i in range(LENGTH // 25 + 1)]
    elevations = [tent(d) for d in distances]
    stats = elevation.profile_stats(distances, elevations, PARAMS)
    (day,) = day_stats([0, LENGTH], distances, smoothed_profile(elevations, PARAMS), PARAMS)
    assert (day["gain_m"], day["loss_m"]) == (stats["gain_m"], stats["loss_m"]) == (194, 192.8)


def test_days_without_a_profile_have_distance_only():
    days = day_stats([0, 1500, LENGTH], None, None, None)
    assert [(d["distance_m"], d["gain_m"], d["loss_m"]) for d in days] == [
        (1500, None, None),
        (2500, None, None),
    ]


def test_a_stop_at_the_same_place_as_another_makes_a_zero_day():
    distances = [i * 25.0 for i in range(LENGTH // 25 + 1)]
    smoothed = smoothed_profile([tent(d) for d in distances], PARAMS)
    days = day_stats([0, 1000, 1000, LENGTH], distances, smoothed, PARAMS)
    assert days[1]["distance_m"] == 0 and days[1]["gain_m"] == 0


# --- API ------------------------------------------------------------------------------------


@pytest.fixture
def network(monkeypatch):
    forecast = json.loads((FIXTURES / "open_meteo_forecast.json").read_text())
    monkeypatch.setattr(
        "analysis.analyses.weather.fetch_json", lambda url, params: copy.deepcopy(forecast)
    )
    monkeypatch.setattr(
        elevation,
        "post_samples",
        lambda points: {
            "samples": [
                {"locationId": i, "value": str(tent(i * 25.0)), "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        },
    )


@pytest.fixture
def route(network):
    line = LineString((X0, Y0), (X0 + LENGTH, Y0), srid=5070)
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/1",
        osm_id=1,
        name="Test Trail",
        geom=MultiLineString(line, srid=5070).transform(4326, clone=True),
        length_m=LENGTH,
        member_way_ids=[10],
    )


def site(source_id, along, off=20, name=None):
    point = Point(X0 + along, Y0 + off, srid=5070).transform(4326, clone=True)
    return Campsite.objects.create(
        source=Campsite.Source.OSM, source_id=source_id, name=name or source_id, geom=point
    )


def client_for(username):
    user = User.objects.create_user(username=username, password="a-strong-passw0rd!")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
    return client


@pytest.fixture
def alice():
    return client_for("alice")


@pytest.fixture
def bob():
    return client_for("bob")


def save(client, stop_ids, **body):
    return client.post("/api/plans/", {"osm_id": 1, "stop_ids": stop_ids, **body}, format="json")


@pytest.mark.django_db
@pytest.mark.integration
def test_preview_orders_stops_along_the_route_and_works_out_each_day(route, alice):
    site("node/far", 3000, name="Upper Camp")
    site("node/near", 1000, name="Lower Camp")

    response = alice.post(
        "/api/plans/preview/", {"osm_id": 1, "stop_ids": ["node/far", "node/near"]}, format="json"
    )

    assert response.status_code == 200
    plan = response.json()
    assert plan["nights"] == 2
    assert [(s["night"], s["display_name"]) for s in plan["stops"]] == [
        (1, "Lower Camp"),
        (2, "Upper Camp"),
    ]
    assert [(d["from"], d["to"]) for d in plan["days"]] == [
        ("Start", "Lower Camp"),
        ("Lower Camp", "Upper Camp"),
        ("Upper Camp", "End"),
    ]
    assert [d["distance_m"] for d in plan["days"]] == pytest.approx([1000, 2000, 1000], abs=0.5)
    # About 100 m each, measured as in test_days_split_the_profile_at_the_stops.
    assert plan["days"][0]["gain_m"] == pytest.approx(100, abs=5)
    assert plan["days"][1]["gain_m"] == pytest.approx(100, abs=5)
    assert plan["days"][1]["loss_m"] == pytest.approx(100, abs=5)
    assert plan["days"][2]["loss_m"] == pytest.approx(100, abs=5)
    assert plan["totals"]["distance_m"] == pytest.approx(LENGTH, abs=0.5)
    assert plan["totals"]["gain_m"] == pytest.approx(200, abs=10)
    assert plan["profile"]["status"] == "ok"
    assert TripPlan.objects.count() == 0  # a preview saves nothing


@pytest.mark.django_db
@pytest.mark.integration
def test_days_come_from_the_stored_profile_without_refetching(route, alice, monkeypatch):
    site("node/a", 2000)
    assert alice.get("/api/routes/1/").status_code == 200  # the panel stores the profile

    def fail(points):
        raise AssertionError("3DEP should not be called again")

    monkeypatch.setattr(elevation, "post_samples", fail)
    plan = alice.post("/api/plans/preview/", {"osm_id": 1, "stop_ids": ["node/a"]}, format="json")
    assert plan.status_code == 200
    assert plan.json()["days"][0]["gain_m"] == 194  # as in the pure tests above


@pytest.mark.django_db
@pytest.mark.integration
def test_without_a_profile_days_have_distance_but_no_climb(route, alice, monkeypatch):
    def down(points):
        raise AnalysisError("3DEP unavailable")

    monkeypatch.setattr(elevation, "post_samples", down)
    site("node/a", 2000)
    plan = alice.post(
        "/api/plans/preview/", {"osm_id": 1, "stop_ids": ["node/a"]}, format="json"
    ).json()
    assert plan["profile"]["status"] == "unavailable"
    assert [d["gain_m"] for d in plan["days"]] == [None, None]
    assert plan["totals"]["gain_m"] is None


@pytest.mark.django_db
@pytest.mark.integration
@pytest.mark.parametrize(
    ("along", "off", "message"),
    [
        (-400, 0, "off the end of Test Trail: it lies before the trail's start"),
        (LENGTH + 400, 0, "off the end of Test Trail: it lies past its end"),
        (2000, 6000, "a stop must be within 5 km of the trail"),
    ],
)
def test_a_stop_off_the_route_is_rejected_with_a_clear_message(route, alice, along, off, message):
    site("node/ok", 1000)
    site("node/bad", along, off, name="Wrong Camp")
    response = save(alice, ["node/ok", "node/bad"])
    assert response.status_code == 400
    assert message in response.json()["error"]
    assert "Wrong Camp" in response.json()["error"]
    assert TripPlan.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.integration
@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"stop_ids": []}, "at least one campsite"),
        ({"stop_ids": ["node/a", "node/a"]}, "only once"),
        ({"stop_ids": ["node/nope"]}, "No campsite with id node/nope"),
        ({"stop_ids": "node/a"}, "must be a list"),
        ({"osm_id": None, "stop_ids": ["node/a"]}, "Say which trail"),
    ],
)
def test_bad_plans_are_rejected(route, alice, body, message):
    site("node/a", 1000)
    response = alice.post("/api/plans/", {"osm_id": 1, **body}, format="json")
    assert response.status_code == 400
    assert message in response.json()["error"]


@pytest.mark.django_db
@pytest.mark.integration
def test_unknown_trail_is_404(route, alice):
    site("node/a", 1000)
    assert save(alice, ["node/a"], osm_id=999).status_code == 404


@pytest.mark.django_db
@pytest.mark.integration
def test_save_reopen_rename_restop_and_delete(route, alice):
    site("node/a", 1000, name="Lower Camp")
    site("node/b", 3000, name="Upper Camp")

    created = save(alice, ["node/b"], name="  Weekend  ")
    assert created.status_code == 201
    plan = created.json()
    assert plan["name"] == "Weekend" and plan["trail_name"] == "Test Trail"
    assert plan["nights"] == 1

    listed = alice.get("/api/plans/").json()
    assert [(p["id"], p["name"], p["nights"]) for p in listed] == [(plan["id"], "Weekend", 1)]
    assert alice.get("/api/plans/", {"osm_id": 1}).json()[0]["id"] == plan["id"]
    assert alice.get("/api/plans/", {"osm_id": 2}).json() == []

    url = f"/api/plans/{plan['id']}/"
    reopened = alice.get(url).json()
    assert [s["id"] for s in reopened["stops"]] == ["node/b"]
    assert len(reopened["days"]) == 2

    changed = alice.patch(
        url, {"name": "Long weekend", "stop_ids": ["node/b", "node/a"]}, format="json"
    ).json()
    assert changed["name"] == "Long weekend"
    assert [s["id"] for s in changed["stops"]] == ["node/a", "node/b"]

    # An invalid change is rejected and changes nothing.
    site("node/off", -400, 0)
    assert alice.patch(url, {"stop_ids": ["node/off"]}, format="json").status_code == 400
    assert [s["id"] for s in alice.get(url).json()["stops"]] == ["node/a", "node/b"]

    assert alice.delete(url).status_code == 204
    assert alice.get(url).status_code == 404
    assert TripPlan.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.integration
def test_a_default_name_is_given(route, alice):
    site("node/a", 1000)
    assert save(alice, ["node/a"]).json()["name"] == "Test Trail: 1 nights"


@pytest.mark.django_db
@pytest.mark.integration
def test_plans_are_per_user(route, alice, bob):
    site("node/a", 1000)
    mine = save(alice, ["node/a"], name="Alice's").json()
    url = f"/api/plans/{mine['id']}/"

    assert bob.get("/api/plans/").json() == []
    assert bob.get(url).status_code == 404
    assert bob.get(f"{url}gpx/").status_code == 404
    assert bob.patch(url, {"name": "Mine"}, format="json").status_code == 404
    assert bob.delete(url).status_code == 404
    assert TripPlan.objects.get().name == "Alice's"

    anonymous = APIClient()
    assert anonymous.get("/api/plans/").status_code == 401
    assert anonymous.post("/api/plans/preview/", {}, format="json").status_code == 401
    assert anonymous.get(url).status_code == 401
    assert anonymous.get(f"{url}gpx/").status_code == 401


@pytest.mark.django_db
@pytest.mark.integration
def test_stops_that_are_not_permitted_carry_a_warning(route, alice, monkeypatch):
    site("node/a", 1000, name="Lean-to")
    site("node/b", 3000, name="Ridge Spot")
    from planning import plans

    real = plans.legality_verdict

    def verdict(site_row, facts, legal_status):
        result = real(site_row, facts, legal_status)
        if site_row.source_id == "node/a":
            return {
                **result,
                "verdict": "permitted",
                "label": "Permitted · designated site",
                "reason": "Designated campsite.",
            }
        return result

    monkeypatch.setattr(plans, "legality_verdict", verdict)
    plan = alice.post(
        "/api/plans/preview/", {"osm_id": 1, "stop_ids": ["node/a", "node/b"]}, format="json"
    ).json()
    first, second = plan["stops"]
    assert first["legality"]["verdict"] == "permitted" and first["warning"] is None
    assert second["legality"]["verdict"] != "permitted"
    assert second["warning"].startswith(f"Night 2, Ridge Spot: {second['legality']['label']}")
    assert plan["warnings"] == [second["warning"]]


@pytest.mark.django_db
@pytest.mark.integration
def test_plan_gpx_has_the_track_the_stops_and_the_users_nearby_waypoints(route, alice, bob):
    site("node/a", 1000, name="Lower Camp")
    site("node/b", 3000, name="Upper Camp")
    site("node/c", 2000, name="Not a stop")
    plan = save(alice, ["node/b", "node/a"], name="Two nights").json()
    near = Point(X0 + 1500, Y0 + 100, srid=5070).transform(4326, clone=True)
    far = Point(X0 + 1500, Y0 + 3000, srid=5070).transform(4326, clone=True)
    for client, name, point in [
        (alice, "Spring", near),
        (alice, "Far away", far),
        (bob, "Bob's", near),
    ]:
        client.post(
            "/api/waypoints/",
            {"name": name, "kind": "water", "lon": point.x, "lat": point.y},
            format="json",
        )

    response = alice.get(f"/api/plans/{plan['id']}/gpx/")

    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="two-nights.gpx"'
    xmlschema.XMLSchema(FIXTURES / "gpx-1.1.xsd").validate(response.content.decode())
    root = ET.fromstring(response.content)
    wpts = [
        (w.find("g:name", NS).text, w.find("g:type", NS).text) for w in root.findall("g:wpt", NS)
    ]
    assert wpts == [
        ("Night 1: Lower Camp", "overnight-stop"),
        ("Night 2: Upper Camp", "overnight-stop"),
        ("Spring", "waypoint:water"),
    ]
    desc = root.find("g:wpt/g:desc", NS).text
    assert desc.startswith("Day 1: 1.0 km. +95 m / -0 m.")
    points = root.findall("g:trk/g:trkseg/g:trkpt", NS)
    assert points and points[0].find("g:ele", NS) is not None


@pytest.mark.django_db
@pytest.mark.integration
def test_a_plan_on_an_assembled_trail_is_kept_by_its_way(network, alice):
    line = LineString((X0, Y0), (X0 + LENGTH, Y0), srid=5070).transform(4326, clone=True)
    Trail.objects.create(
        source=Trail.Source.OSM,
        source_id="way/77",
        name="Lonely Path",
        geom=MultiLineString(line, srid=4326),
        osm_node_ids=[1, 2],
    )
    site("node/a", 2000)
    created = alice.post(
        "/api/plans/", {"from_way": "way/77", "stop_ids": ["node/a"]}, format="json"
    ).json()
    assert created["osm_id"] is None and created["from_way"] == "way/77"
    assert created["trail_name"] == "Lonely Path"
    assert alice.get("/api/plans/", {"from_way": "way/77"}).json()[0]["id"] == created["id"]
    assert alice.get(f"/api/plans/{created['id']}/").json()["nights"] == 1


@pytest.mark.django_db
@pytest.mark.integration
def test_deleting_the_account_deletes_its_plans(route, alice):
    site("node/a", 1000)
    save(alice, ["node/a"])
    assert alice.delete("/api/auth/me/").status_code == 204
    assert TripPlan.objects.count() == 0
