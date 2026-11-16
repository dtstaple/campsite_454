"""
Shareable trip plan links (TM05-172): the owner creates a read-only link with a long random
token, anyone can open it without signing in, it never shows the owner's account, and once
revoked it stops working.

Uses the straight 4 km test route and tent-shaped profile from test_plans.py.
"""

import json

import pytest
from rest_framework.test import APIClient
from test_plans import client_for, network, route, save, site  # noqa: F401 (fixtures)

from planning.models import TripPlan


@pytest.fixture
def alice():
    return client_for("alice")


@pytest.fixture
def bob():
    return client_for("bob")


@pytest.fixture
def plan_id(route, alice):  # noqa: F811
    site("node/near", 1000, name="Lower Camp")
    site("node/far", 3000, name="Upper Camp")
    response = save(alice, ["node/far", "node/near"], name="Two nights")
    assert response.status_code == 201
    return response.json()["id"]


def share(client, plan_id):
    return client.post(f"/api/plans/{plan_id}/share/")


@pytest.mark.django_db
@pytest.mark.integration
def test_the_owner_creates_a_long_random_link_once(plan_id, alice):
    first = share(alice, plan_id)

    assert first.status_code == 201
    token = first.json()["token"]
    assert len(token) >= 40  # 32 random bytes, URL-safe base64
    assert first.json()["path"] == f"/shared/{token}"
    # Sharing again keeps the same link; the owner's own view of the plan shows it.
    again = share(alice, plan_id)
    assert again.status_code == 200 and again.json()["token"] == token
    assert alice.get(f"/api/plans/{plan_id}/").json()["share_token"] == token


@pytest.mark.django_db
@pytest.mark.integration
def test_each_plan_gets_its_own_token(plan_id, alice):
    other = save(alice, ["node/near"]).json()["id"]
    assert share(alice, plan_id).json()["token"] != share(alice, other).json()["token"]


@pytest.mark.django_db
@pytest.mark.integration
def test_anyone_can_open_the_link_without_signing_in(plan_id, alice):
    token = share(alice, plan_id).json()["token"]

    response = APIClient().get(f"/api/shared/{token}/")

    assert response.status_code == 200
    plan = response.json()
    assert plan["name"] == "Two nights"
    assert plan["trail"]["name"] == "Test Trail"
    assert plan["nights"] == 2
    assert [s["display_name"] for s in plan["stops"]] == ["Lower Camp", "Upper Camp"]
    assert [d["distance_m"] for d in plan["days"]] == pytest.approx([1000, 2000, 1000], abs=0.5)
    assert plan["days"][0]["gain_m"] == pytest.approx(100, abs=5)
    assert plan["totals"]["distance_m"] == pytest.approx(4000, abs=0.5)


@pytest.mark.django_db
@pytest.mark.integration
def test_the_shared_plan_never_shows_the_owner(plan_id, alice):
    token = share(alice, plan_id).json()["token"]
    owner = TripPlan.objects.get(pk=plan_id).user
    owner.email = "alice@example.com"
    owner.save()

    body = APIClient().get(f"/api/shared/{token}/").json()

    text = json.dumps(body)
    assert "alice" not in text
    for key in ("id", "user", "username", "email", "share_token", "created_at", "updated_at"):
        assert key not in body


@pytest.mark.django_db
@pytest.mark.integration
def test_revoking_ends_access_and_sharing_again_makes_a_new_link(plan_id, alice):
    token = share(alice, plan_id).json()["token"]

    assert alice.delete(f"/api/plans/{plan_id}/share/").status_code == 204

    assert APIClient().get(f"/api/shared/{token}/").status_code == 404
    assert alice.get(f"/api/shared/{token}/").status_code == 404  # not even for the owner
    assert alice.get(f"/api/plans/{plan_id}/").json()["share_token"] is None
    fresh = share(alice, plan_id).json()["token"]
    assert fresh != token
    assert APIClient().get(f"/api/shared/{fresh}/").status_code == 200
    assert APIClient().get(f"/api/shared/{token}/").status_code == 404


@pytest.mark.django_db
@pytest.mark.integration
def test_only_the_owner_can_share_or_revoke(plan_id, alice, bob):
    token = share(alice, plan_id).json()["token"]

    assert share(bob, plan_id).status_code == 404
    assert bob.delete(f"/api/plans/{plan_id}/share/").status_code == 404
    assert APIClient().post(f"/api/plans/{plan_id}/share/").status_code == 401
    assert APIClient().get(f"/api/shared/{token}/").status_code == 200  # still shared


@pytest.mark.django_db
@pytest.mark.integration
def test_an_unknown_token_is_404(plan_id):
    assert APIClient().get("/api/shared/not-a-real-token/").status_code == 404


@pytest.mark.django_db
@pytest.mark.integration
def test_deleting_the_plan_ends_the_link(plan_id, alice):
    token = share(alice, plan_id).json()["token"]
    assert alice.delete(f"/api/plans/{plan_id}/").status_code == 204
    assert APIClient().get(f"/api/shared/{token}/").status_code == 404
