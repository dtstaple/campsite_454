"""
Deleting an account (TM05-70): DELETE /api/auth/me/.

The guarantees are what deletion removes (the user, their token, their saved campsites),
what it leaves alone (the campsites themselves, every other account), and that nothing
happens without a valid token. Row counts are checked directly, because "the endpoint
said 204" is not the same as "the data is gone".
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.db import models
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import SavedCampsite
from geodata.models import Campsite

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

User = get_user_model()

ME_URL = "/api/auth/me/"


def campsite(source_id):
    return Campsite.objects.create(
        source=Campsite.Source.OSM,
        source_id=source_id,
        name=source_id,
        geom=Point(-73.95, 44.18, srid=4326),
    )


def account(username, *sites):
    """A user with a token and the given campsites saved, plus a client carrying it."""
    user = User.objects.create_user(username=username, password="a-strong-passw0rd!")
    token = Token.objects.create(user=user)
    for site in sites:
        SavedCampsite.objects.create(user=user, campsite=site)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return user, token, client


def counts():
    return (User.objects.count(), Token.objects.count(), SavedCampsite.objects.count())


def test_delete_removes_the_user_their_token_and_their_saved_campsites():
    marcy, lake = campsite("node/1"), campsite("node/2")
    user, token, client = account("rania", marcy, lake)

    response = client.delete(ME_URL)

    assert response.status_code == 204
    assert not response.content
    assert not User.objects.filter(pk=user.pk).exists()
    assert not Token.objects.filter(key=token.key).exists()
    assert not SavedCampsite.objects.filter(user_id=user.pk).exists()
    # The campsites are shared reference data, not the user's: they stay.
    assert Campsite.objects.filter(pk__in=[marcy.pk, lake.pk]).count() == 2


def test_the_token_stops_working_after_the_account_is_deleted():
    _, _, client = account("rania")
    client.delete(ME_URL)

    assert client.get(ME_URL).status_code == 401
    assert client.delete(ME_URL).status_code == 401


@pytest.mark.parametrize("header", [None, "Token not-a-real-token"])
def test_without_a_valid_token_it_is_401_and_nothing_is_deleted(header):
    account("rania", campsite("node/1"))
    before = counts()
    client = APIClient()
    if header:
        client.credentials(HTTP_AUTHORIZATION=header)

    response = client.delete(ME_URL)

    assert response.status_code == 401
    assert counts() == before == (1, 1, 1)


def test_another_users_account_token_and_saves_are_untouched():
    shared = campsite("node/1")
    _, _, client = account("rania", shared, campsite("node/2"))
    davis, davis_token, davis_client = account("davis", shared)

    client.delete(ME_URL)

    assert User.objects.filter(pk=davis.pk).exists()
    assert Token.objects.filter(key=davis_token.key).exists()
    assert list(SavedCampsite.objects.filter(user=davis).values_list("campsite", flat=True)) == [
        shared.pk
    ]
    assert davis_client.get(ME_URL).json()["username"] == "davis"
    assert counts() == (1, 1, 1)


def test_every_foreign_key_to_the_user_cascades():
    """Deletion relies on CASCADE (accounts/views.py). A new model pointing at the user
    with PROTECT, SET_NULL or DO_NOTHING would make deletion fail or leave orphans; this
    test names it so the delete endpoint is updated with it."""
    relations = [rel for rel in User._meta.related_objects if isinstance(rel, models.ManyToOneRel)]
    labels = {rel.related_model._meta.label for rel in relations}
    assert {"accounts.SavedCampsite", "authtoken.Token"} <= labels
    not_cascading = [
        rel.related_model._meta.label for rel in relations if rel.on_delete is not models.CASCADE
    ]
    assert not_cascading == []
