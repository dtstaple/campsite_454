"""
Save / unsave a campsite.

Both endpoints require a token (401 with none, never a 403 or a crash) and 404 when the
campsite id doesn't exist -- checked before creating any state, so a bad id can never
half-succeed.

The id in the URL is the campsite's source_id, which is what the map API puts in each
GeoJSON Feature's `id`. It contains a slash, so these tests also pin the routing: a
converter that cannot match "campsite/73996" would 404 every real campsite.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import SavedCampsite
from geodata.models import Campsite

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

User = get_user_model()

NONEXISTENT_ID = "campsite/999999"


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user():
    return User.objects.create_user(username="rania", password="a-strong-passw0rd!")


@pytest.fixture
def token(user):
    return Token.objects.create(user=user).key


@pytest.fixture
def auth_client(client, token):
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    return client


@pytest.fixture
def campsite():
    return Campsite.objects.create(
        source=Campsite.Source.RIDB,
        source_id="campsite/73996",
        name="Marcy Dam",
        geom=Point(-74.05, 44.10, srid=4326),
        site_type=Campsite.SiteType.LEAN_TO,
    )


def saved_url(source_id):
    return f"/api/saved-campsites/{source_id}/"


# --- saving -----------------------------------------------------------------------------


def test_saving_with_a_valid_token_succeeds_and_creates_a_row(auth_client, user, campsite):
    response = auth_client.post(saved_url(campsite.source_id))

    assert response.status_code == 201
    assert SavedCampsite.objects.filter(user=user, campsite=campsite).exists()


def test_saving_the_same_campsite_twice_does_not_duplicate(auth_client, user, campsite):
    first = auth_client.post(saved_url(campsite.source_id))
    second = auth_client.post(saved_url(campsite.source_id))

    assert first.status_code == 201
    assert second.status_code == 200
    assert SavedCampsite.objects.filter(user=user, campsite=campsite).count() == 1


def test_saving_without_a_token_returns_401(client, campsite):
    response = client.post(saved_url(campsite.source_id))

    assert response.status_code == 401
    assert not SavedCampsite.objects.exists()


def test_saving_a_nonexistent_campsite_returns_404(auth_client):
    response = auth_client.post(saved_url(NONEXISTENT_ID))

    assert response.status_code == 404
    assert not SavedCampsite.objects.exists()


def test_two_users_can_each_save_the_same_campsite(auth_client, user, campsite):
    other = User.objects.create_user(username="other", password="another-strong-pw!")
    other_client = APIClient()
    other_client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=other).key}")

    auth_client.post(saved_url(campsite.source_id))
    other_client.post(saved_url(campsite.source_id))

    assert SavedCampsite.objects.filter(campsite=campsite).count() == 2


# --- unsaving ---------------------------------------------------------------------------


def test_unsaving_removes_the_row(auth_client, user, campsite):
    auth_client.post(saved_url(campsite.source_id))

    response = auth_client.delete(saved_url(campsite.source_id))

    assert response.status_code == 204
    assert not SavedCampsite.objects.filter(user=user, campsite=campsite).exists()


def test_unsaving_without_a_token_returns_401(client, user, campsite):
    SavedCampsite.objects.create(user=user, campsite=campsite)

    response = client.delete(saved_url(campsite.source_id))

    assert response.status_code == 401
    assert SavedCampsite.objects.filter(user=user, campsite=campsite).exists()


def test_unsaving_a_nonexistent_campsite_returns_404(auth_client):
    response = auth_client.delete(saved_url(NONEXISTENT_ID))

    assert response.status_code == 404


def test_unsaving_something_never_saved_returns_404(auth_client, campsite):
    response = auth_client.delete(saved_url(campsite.source_id))

    assert response.status_code == 404


# --- the round trip ---------------------------------------------------------------------
#
# The bug this covers: the map API used to emit source_id as the Feature id while the save
# endpoint routed on the primary key, so the only identifier a client ever held was the one
# identifier the endpoint refused. Every save from the map 404'd. Asserting the two halves
# in separate tests is what let that through -- each side was correct alone. This test is
# deliberately end to end: whatever the map API says a campsite is called, saving it by
# that exact string has to work.


def test_a_campsite_fetched_from_the_map_api_can_be_saved_by_the_id_it_came_with(
    auth_client, user, campsite
):
    listing = auth_client.get("/api/campsites/?bbox=-74.20,44.00,-73.90,44.20")
    assert listing.status_code == 200

    features = listing.json()["features"]
    assert len(features) == 1, "fixture campsite should be the only one in the bbox"
    feature_id = features[0]["id"]

    # The identifier the client holds, used verbatim -- no parsing, no lookup, no guessing.
    response = auth_client.post(saved_url(feature_id))

    assert (
        response.status_code == 201
    ), f"the map API handed the client id {feature_id!r} and the save endpoint rejected it"
    assert SavedCampsite.objects.filter(user=user, campsite=campsite).exists()


def test_the_map_api_feature_id_is_the_campsites_source_id(auth_client, campsite):
    listing = auth_client.get("/api/campsites/?bbox=-74.20,44.00,-73.90,44.20")

    assert listing.json()["features"][0]["id"] == campsite.source_id


# --- listing ----------------------------------------------------------------------------
#
# The list is what makes saving worth anything: before this endpoint a user could save a
# campsite and never see it again. Two properties matter beyond "it returns rows". First,
# each entry carries enough to render a list row and move the map -- a name and a pair of
# coordinates -- so the frontend needs no second request per saved site. Second, the `id`
# is the same source_id the map API puts in each Feature, which is what lets the map mark
# its own pins as saved.


LIST_URL = "/api/saved-campsites/"


@pytest.fixture
def other_campsite():
    return Campsite.objects.create(
        source=Campsite.Source.OSM,
        source_id="node/4821",
        name="Flowed Lands",
        geom=Point(-73.98, 44.12, srid=4326),
        site_type=Campsite.SiteType.PRIMITIVE,
    )


def test_listing_returns_the_users_saved_campsites(auth_client, user, campsite):
    SavedCampsite.objects.create(user=user, campsite=campsite)

    response = auth_client.get(LIST_URL)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == campsite.source_id
    assert body[0]["name"] == "Marcy Dam"


def test_a_listed_entry_carries_enough_to_render_it_and_move_the_map(auth_client, user, campsite):
    SavedCampsite.objects.create(user=user, campsite=campsite)

    entry = auth_client.get(LIST_URL).json()[0]

    assert entry["name"] == "Marcy Dam"
    assert entry["site_type"] == "lean_to"
    # The coordinates the map needs to fly to, as plain numbers rather than GeoJSON.
    assert entry["latitude"] == pytest.approx(44.10)
    assert entry["longitude"] == pytest.approx(-74.05)
    assert entry["saved_at"]


def test_unknown_reservable_stays_null_rather_than_false(auth_client, user, campsite):
    # The fixture campsite leaves reservable unset, which the model documents as "the
    # source didn't say". Serialising that as false would assert something untrue.
    assert campsite.reservable is None
    SavedCampsite.objects.create(user=user, campsite=campsite)

    entry = auth_client.get(LIST_URL).json()[0]

    assert entry["reservable"] is None
    assert entry["capacity"] is None


def test_listing_returns_an_empty_list_when_nothing_is_saved(auth_client):
    response = auth_client.get(LIST_URL)

    assert response.status_code == 200
    assert response.json() == []


def test_listing_without_a_token_returns_401(client, user, campsite):
    SavedCampsite.objects.create(user=user, campsite=campsite)

    response = client.get(LIST_URL)

    assert response.status_code == 401


def test_listing_with_a_garbage_token_returns_401(client):
    client.credentials(HTTP_AUTHORIZATION="Token not-a-real-token")

    response = client.get(LIST_URL)

    assert response.status_code == 401


def test_one_user_cannot_see_another_users_saved_campsites(
    auth_client, user, campsite, other_campsite
):
    other = User.objects.create_user(username="other", password="another-strong-pw!")
    SavedCampsite.objects.create(user=other, campsite=other_campsite)
    SavedCampsite.objects.create(user=user, campsite=campsite)

    body = auth_client.get(LIST_URL).json()

    assert [entry["id"] for entry in body] == [campsite.source_id]


def test_a_user_with_no_saves_sees_an_empty_list_even_when_others_have_saved(auth_client, campsite):
    other = User.objects.create_user(username="other", password="another-strong-pw!")
    SavedCampsite.objects.create(user=other, campsite=campsite)

    assert auth_client.get(LIST_URL).json() == []


def test_listing_is_newest_first(auth_client, user, campsite, other_campsite):
    older = SavedCampsite.objects.create(user=user, campsite=campsite)
    newer = SavedCampsite.objects.create(user=user, campsite=other_campsite)
    # created_at is auto_now_add, so two rows inserted in the same test are microseconds
    # apart and their order is technically a race. Setting the timestamps through an
    # UPDATE (which auto_now_add does not touch) makes the assertion about ordering
    # rather than about how fast the test ran.
    SavedCampsite.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
    SavedCampsite.objects.filter(pk=newer.pk).update(created_at=timezone.now())

    body = auth_client.get(LIST_URL).json()

    assert [entry["id"] for entry in body] == [other_campsite.source_id, campsite.source_id]


def test_saving_then_listing_round_trips_the_map_api_feature_id(auth_client, campsite):
    listing = auth_client.get("/api/campsites/?bbox=-74.20,44.00,-73.90,44.20")
    feature_id = listing.json()["features"][0]["id"]

    auth_client.post(saved_url(feature_id))

    saved_ids = [entry["id"] for entry in auth_client.get(LIST_URL).json()]
    assert saved_ids == [feature_id], (
        "the id the map handed the client must come back unchanged from the saved list, "
        "or the frontend cannot tell which pins are already saved"
    )


def test_unsaving_removes_the_entry_from_the_list(auth_client, user, campsite):
    auth_client.post(saved_url(campsite.source_id))
    assert len(auth_client.get(LIST_URL).json()) == 1

    auth_client.delete(saved_url(campsite.source_id))

    assert auth_client.get(LIST_URL).json() == []
