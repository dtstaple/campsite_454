"""
Save / unsave a campsite.

Both endpoints require a token (401 with none, never a 403 or a crash) and 404 when the
campsite id doesn't exist -- checked before creating any state, so a bad id can never
half-succeed.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import SavedCampsite
from geodata.models import Campsite

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

User = get_user_model()

NONEXISTENT_ID = 999_999


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
        source_id="c1",
        name="Marcy Dam",
        geom=Point(-74.05, 44.10, srid=4326),
        site_type=Campsite.SiteType.LEAN_TO,
    )


def saved_url(campsite_id):
    return f"/api/saved-campsites/{campsite_id}/"


# --- saving -----------------------------------------------------------------------------


def test_saving_with_a_valid_token_succeeds_and_creates_a_row(auth_client, user, campsite):
    response = auth_client.post(saved_url(campsite.pk))

    assert response.status_code == 201
    assert SavedCampsite.objects.filter(user=user, campsite=campsite).exists()


def test_saving_the_same_campsite_twice_does_not_duplicate(auth_client, user, campsite):
    first = auth_client.post(saved_url(campsite.pk))
    second = auth_client.post(saved_url(campsite.pk))

    assert first.status_code == 201
    assert second.status_code == 200
    assert SavedCampsite.objects.filter(user=user, campsite=campsite).count() == 1


def test_saving_without_a_token_returns_401(client, campsite):
    response = client.post(saved_url(campsite.pk))

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

    auth_client.post(saved_url(campsite.pk))
    other_client.post(saved_url(campsite.pk))

    assert SavedCampsite.objects.filter(campsite=campsite).count() == 2


# --- unsaving ---------------------------------------------------------------------------


def test_unsaving_removes_the_row(auth_client, user, campsite):
    auth_client.post(saved_url(campsite.pk))

    response = auth_client.delete(saved_url(campsite.pk))

    assert response.status_code == 204
    assert not SavedCampsite.objects.filter(user=user, campsite=campsite).exists()


def test_unsaving_without_a_token_returns_401(client, user, campsite):
    SavedCampsite.objects.create(user=user, campsite=campsite)

    response = client.delete(saved_url(campsite.pk))

    assert response.status_code == 401
    assert SavedCampsite.objects.filter(user=user, campsite=campsite).exists()


def test_unsaving_a_nonexistent_campsite_returns_404(auth_client):
    response = auth_client.delete(saved_url(NONEXISTENT_ID))

    assert response.status_code == 404


def test_unsaving_something_never_saved_returns_404(auth_client, campsite):
    response = auth_client.delete(saved_url(campsite.pk))

    assert response.status_code == 404
