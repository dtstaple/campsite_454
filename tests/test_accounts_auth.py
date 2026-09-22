"""
Registration and login for the accounts app.

Registration and login must never let a caller distinguish "no account with that
email/username" from "wrong password" or "email already taken" -- see accounts/views.py
for why. These tests assert on status codes and response shape rather than on internals,
since the guarantee that matters is what a client (or attacker) can observe over HTTP.
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

User = get_user_model()

REGISTER_URL = "/api/auth/register/"
LOGIN_URL = "/api/auth/login/"


@pytest.fixture
def client():
    return APIClient()


def register(client, username="rania", email="rania@example.com", password="a-strong-passw0rd!"):
    return client.post(
        REGISTER_URL,
        {"username": username, "email": email, "password": password},
        format="json",
    )


# --- registration -----------------------------------------------------------------------


def test_registration_succeeds_and_returns_201(client):
    response = register(client)

    assert response.status_code == 201
    assert response.json() == {"username": "rania", "email": "rania@example.com"}
    assert User.objects.filter(username="rania").exists()


def test_registration_hashes_the_password(client):
    register(client, password="a-strong-passw0rd!")

    user = User.objects.get(username="rania")
    assert user.password != "a-strong-passw0rd!"
    assert user.check_password("a-strong-passw0rd!")


def test_duplicate_email_still_returns_201_but_does_not_create_a_second_account(client):
    register(client, username="first-user", email="taken@example.com")

    response = register(client, username="second-user", email="taken@example.com")

    assert response.status_code == 201
    assert response.json() == {"username": "second-user", "email": "taken@example.com"}
    assert User.objects.filter(email__iexact="taken@example.com").count() == 1
    assert not User.objects.filter(username="second-user").exists()


def test_duplicate_username_is_rejected(client):
    register(client, username="dupe", email="one@example.com")

    response = register(client, username="dupe", email="two@example.com")

    assert response.status_code == 400
    assert User.objects.filter(username="dupe").count() == 1


def test_weak_password_is_rejected(client):
    response = register(client, password="password")

    assert response.status_code == 400
    assert not User.objects.filter(username="rania").exists()


def test_password_too_similar_to_username_is_rejected(client):
    response = register(client, username="marcydam2026", password="marcydam2026")

    assert response.status_code == 400
    assert not User.objects.filter(username="marcydam2026").exists()


# --- login ------------------------------------------------------------------------------


def test_login_with_valid_credentials_returns_a_token(client):
    register(client, username="rania", password="a-strong-passw0rd!")

    response = client.post(
        LOGIN_URL, {"username": "rania", "password": "a-strong-passw0rd!"}, format="json"
    )

    assert response.status_code == 200
    token = response.json()["token"]
    assert token == Token.objects.get(user__username="rania").key


def test_login_with_wrong_password_returns_401(client):
    register(client, username="rania", password="a-strong-passw0rd!")

    response = client.post(
        LOGIN_URL, {"username": "rania", "password": "totally-wrong"}, format="json"
    )

    assert response.status_code == 401
    assert response.json() == {"error": "Invalid credentials."}


def test_login_with_nonexistent_user_returns_401_identically_to_wrong_password(client):
    register(client, username="rania", password="a-strong-passw0rd!")

    wrong_password = client.post(
        LOGIN_URL, {"username": "rania", "password": "totally-wrong"}, format="json"
    )
    no_such_user = client.post(
        LOGIN_URL, {"username": "does-not-exist", "password": "totally-wrong"}, format="json"
    )

    assert no_such_user.status_code == wrong_password.status_code == 401
    assert no_such_user.json() == wrong_password.json() == {"error": "Invalid credentials."}
