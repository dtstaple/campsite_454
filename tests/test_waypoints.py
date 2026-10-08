"""
Custom waypoints (TM05-80): create, edit, delete, signed-out access, cross-user isolation,
and the user's own waypoints in a route's GPX export.
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
from geodata.models import TrailRoute
from planning.models import Waypoint
from planning.views import MAX_WAYPOINTS_PER_USER

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

User = get_user_model()
FIXTURES = Path(__file__).parent / "fixtures"
NS = {"g": "http://www.topografix.com/GPX/1/1"}


def client_for(username):
    user = User.objects.create_user(username=username, password="a-strong-passw0rd!")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
    return user, client


@pytest.fixture
def alice():
    return client_for("alice")


@pytest.fixture
def bob():
    return client_for("bob")


def create(client, **fields):
    body = {"name": "Spring", "kind": "water", "lon": -73.95, "lat": 44.16, **fields}
    return client.post("/api/waypoints/", body, format="json")


# --- create / read --------------------------------------------------------------------------


def test_create_returns_the_waypoint_with_lon_lat(alice):
    user, client = alice
    response = create(client, note="Reliable in August")
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Spring"
    assert body["kind"] == "water" and body["kind_label"] == "Water"
    assert body["note"] == "Reliable in August"
    assert (body["lon"], body["lat"]) == (-73.95, 44.16)
    stored = Waypoint.objects.get(pk=body["id"])
    assert stored.user == user
    assert (stored.geom.x, stored.geom.y) == pytest.approx((-73.95, 44.16))


@pytest.mark.parametrize("kind", ["water", "camp", "bailout", "custom"])
def test_every_kind_can_be_created(alice, kind):
    assert create(alice[1], kind=kind).status_code == 201


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "helipad"},
        {"name": "   "},
        {"lat": 91},
        {"lon": -181},
        {"lon": None},
    ],
)
def test_invalid_waypoints_are_rejected(alice, fields):
    assert create(alice[1], **fields).status_code == 400
    assert Waypoint.objects.count() == 0


def test_list_is_the_users_waypoints_in_creation_order(alice):
    client = alice[1]
    create(client, name="First")
    create(client, name="Second", kind="camp")
    body = client.get("/api/waypoints/").json()
    assert [w["name"] for w in body] == ["First", "Second"]


def test_there_is_a_cap_per_user(alice, monkeypatch):
    monkeypatch.setattr("planning.views.MAX_WAYPOINTS_PER_USER", 2)
    client = alice[1]
    assert create(client).status_code == 201
    assert create(client).status_code == 201
    response = create(client)
    assert response.status_code == 400
    assert "2 waypoints" in response.json()["error"]
    assert MAX_WAYPOINTS_PER_USER >= 100  # the real cap is generous


# --- edit / delete ---------------------------------------------------------------------------


def test_rename_retype_move_and_edit_the_note(alice):
    client = alice[1]
    waypoint = create(client).json()
    url = f"/api/waypoints/{waypoint['id']}/"

    renamed = client.patch(url, {"name": "Upper spring"}, format="json").json()
    assert renamed["name"] == "Upper spring" and renamed["kind"] == "water"

    noted = client.patch(url, {"note": "Dry in 2025"}, format="json").json()
    assert noted["note"] == "Dry in 2025" and noted["name"] == "Upper spring"

    retyped = client.patch(url, {"kind": "bailout"}, format="json").json()
    assert retyped["kind"] == "bailout" and retyped["kind_label"] == "Bail-out"

    moved = client.patch(url, {"lat": 44.2}, format="json").json()
    assert (moved["lon"], moved["lat"]) == (-73.95, 44.2)

    assert client.patch(url, {"name": ""}, format="json").status_code == 400
    assert client.get(url).json()["name"] == "Upper spring"


def test_delete(alice):
    client = alice[1]
    waypoint = create(client).json()
    url = f"/api/waypoints/{waypoint['id']}/"
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.delete(url).status_code == 404
    assert Waypoint.objects.count() == 0


# --- signed out -------------------------------------------------------------------------------


def test_signed_out_requests_are_401_and_change_nothing(alice):
    waypoint = create(alice[1]).json()
    anonymous = APIClient()
    url = f"/api/waypoints/{waypoint['id']}/"
    assert anonymous.get("/api/waypoints/").status_code == 401
    assert create(anonymous).status_code == 401
    assert anonymous.get(url).status_code == 401
    assert anonymous.patch(url, {"name": "x"}, format="json").status_code == 401
    assert anonymous.delete(url).status_code == 401
    assert Waypoint.objects.get().name == "Spring"


def test_a_bad_token_is_401():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token not-a-real-token")
    assert client.get("/api/waypoints/").status_code == 401


# --- isolation --------------------------------------------------------------------------------


def test_users_can_never_read_or_change_each_others_waypoints(alice, bob):
    mine = create(alice[1], name="Alice's spring").json()
    create(bob[1], name="Bob's camp", kind="camp")
    bob_client = bob[1]
    url = f"/api/waypoints/{mine['id']}/"

    assert [w["name"] for w in bob_client.get("/api/waypoints/").json()] == ["Bob's camp"]
    # 404, not 403: another user's id is indistinguishable from one that doesn't exist.
    assert bob_client.get(url).status_code == 404
    assert bob_client.patch(url, {"name": "Mine now"}, format="json").status_code == 404
    assert bob_client.delete(url).status_code == 404
    assert Waypoint.objects.get(pk=mine["id"]).name == "Alice's spring"


def test_the_owner_cannot_be_changed_through_the_api(alice, bob):
    bob_user = bob[0]
    created = create(alice[1], user=bob_user.pk).json()
    assert Waypoint.objects.get(pk=created["id"]).user == alice[0]


def test_deleting_the_account_deletes_its_waypoints(alice):
    user, client = alice
    create(client)
    assert client.delete("/api/auth/me/").status_code == 204
    assert Waypoint.objects.count() == 0


# --- GPX ----------------------------------------------------------------------------------------

X0, Y0 = 1_770_000.0, 2_550_000.0


@pytest.fixture
def route(monkeypatch):
    forecast = json.loads((FIXTURES / "open_meteo_forecast.json").read_text())
    monkeypatch.setattr(
        "analysis.analyses.weather.fetch_json", lambda url, params: copy.deepcopy(forecast)
    )
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
    line = LineString((X0, Y0), (X0 + 4000, Y0), srid=5070)
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/1",
        osm_id=1,
        name="Test Trail",
        geom=MultiLineString(line, srid=5070).transform(4326, clone=True),
        length_m=4000,
        member_way_ids=[10],
    )


def near_route(x, y):
    point = Point(X0 + x, Y0 + y, srid=5070).transform(4326, clone=True)
    return {"lon": round(point.x, 6), "lat": round(point.y, 6)}


def gpx_waypoints(response):
    xmlschema.XMLSchema(FIXTURES / "gpx-1.1.xsd").validate(response.content.decode())
    root = ET.fromstring(response.content)
    return {
        w.find("g:name", NS).text: (w.find("g:sym", NS).text, w.find("g:type", NS).text)
        for w in root.findall("g:wpt", NS)
    }


def test_the_users_nearby_waypoints_are_in_the_route_gpx(route, alice, bob):
    create(alice[1], name="Spring by the trail", **near_route(1000, 100))
    create(alice[1], name="Far bail-out", kind="bailout", **near_route(2000, 3000))
    create(bob[1], name="Bob's camp", kind="camp", **near_route(1500, 50))

    mine = gpx_waypoints(alice[1].get("/api/routes/1/gpx/"))
    assert mine == {"Spring by the trail": ("Drinking Water", "waypoint:water")}

    # Bob sees his own; a signed-out download has none.
    assert set(gpx_waypoints(bob[1].get("/api/routes/1/gpx/"))) == {"Bob's camp"}
    assert gpx_waypoints(APIClient().get("/api/routes/1/gpx/")) == {}

    # The distance is the same one the campsites use.
    wide = gpx_waypoints(alice[1].get("/api/routes/1/gpx/", {"campsites_within_m": 5000}))
    assert set(wide) == {"Spring by the trail", "Far bail-out"}
