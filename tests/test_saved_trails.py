"""
Saved trails (TM05-100): save, list, unsave, saving twice, assembled trails, signed-out
access and per-user isolation.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import LineString, MultiLineString
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from geodata.models import METRIC_SRID, Trail, TrailRoute
from planning.models import SavedTrail

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

X0, Y0 = 1_770_000.0, 2_550_000.0


def geom(length=2000):
    line = LineString((X0, Y0), (X0 + length, Y0), srid=METRIC_SRID)
    return MultiLineString(line.transform(4326, clone=True), srid=4326)


@pytest.fixture
def route():
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/7",
        osm_id=7,
        name="Saved Trail",
        geom=geom(),
        length_m=2000,
        member_way_ids=[70],
    )


@pytest.fixture
def lonely_way():
    return Trail.objects.create(
        source=Trail.Source.OSM,
        source_id="way/77",
        name="Lonely Path",
        geom=geom(1500),
        length_m=1500,
        osm_node_ids=[1, 2],
    )


def client_for(username):
    user = get_user_model().objects.create_user(username=username, password="a-strong-passw0rd!")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
    return client


@pytest.fixture
def alice():
    return client_for("alice")


@pytest.fixture
def bob():
    return client_for("bob")


def test_save_list_and_unsave_a_route(alice, route):
    created = alice.post("/api/saved-trails/", {"osm_id": 7}, format="json")
    assert created.status_code == 201
    body = created.json()
    assert (body["osm_id"], body["from_way"], body["name"], body["length_m"]) == (
        7,
        None,
        "Saved Trail",
        2000,
    )
    assert [t["id"] for t in alice.get("/api/saved-trails/").json()] == [body["id"]]
    assert alice.delete(f"/api/saved-trails/{body['id']}/").status_code == 204
    assert alice.get("/api/saved-trails/").json() == []
    assert alice.delete(f"/api/saved-trails/{body['id']}/").status_code == 404


def test_saving_twice_is_one_saved_trail(alice, route):
    first = alice.post("/api/saved-trails/", {"osm_id": 7}, format="json")
    again = alice.post("/api/saved-trails/", {"osm_id": 7}, format="json")
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    assert SavedTrail.objects.count() == 1


def test_an_assembled_trail_is_saved_by_its_way(alice, lonely_way):
    body = alice.post("/api/saved-trails/", {"from_way": "way/77"}, format="json").json()
    assert (body["osm_id"], body["from_way"], body["name"]) == (None, "way/77", "Lonely Path")
    again = alice.post("/api/saved-trails/", {"from_way": "way/77"}, format="json")
    assert again.status_code == 200


def test_bad_and_unknown_trails(alice):
    assert alice.post("/api/saved-trails/", {}, format="json").status_code == 400
    assert alice.post("/api/saved-trails/", {"osm_id": "x"}, format="json").status_code == 400
    assert alice.post("/api/saved-trails/", {"osm_id": 999}, format="json").status_code == 404
    assert (
        alice.post("/api/saved-trails/", {"from_way": "way/999"}, format="json").status_code == 404
    )


def test_signed_out_is_401(route):
    anonymous = APIClient()
    assert anonymous.get("/api/saved-trails/").status_code == 401
    assert anonymous.post("/api/saved-trails/", {"osm_id": 7}, format="json").status_code == 401
    assert anonymous.delete("/api/saved-trails/1/").status_code == 401


def test_saved_trails_are_per_user(alice, bob, route):
    mine = alice.post("/api/saved-trails/", {"osm_id": 7}, format="json").json()
    assert bob.get("/api/saved-trails/").json() == []
    # 404, not 403: someone else's id looks like one that doesn't exist.
    assert bob.delete(f"/api/saved-trails/{mine['id']}/").status_code == 404
    assert SavedTrail.objects.filter(pk=mine["id"]).exists()
    # Bob saving the same trail is his own row.
    assert bob.post("/api/saved-trails/", {"osm_id": 7}, format="json").status_code == 201
    assert SavedTrail.objects.count() == 2


def test_deleting_the_account_deletes_its_saved_trails(alice, route):
    alice.post("/api/saved-trails/", {"osm_id": 7}, format="json")
    assert alice.delete("/api/auth/me/").status_code == 204
    assert SavedTrail.objects.count() == 0
