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


# --- logout -----------------------------------------------------------------------------
#
# The guarantee being tested is revocation, not the 204. A logout that returned 204 and
# left the token working would pass a status-code assertion and still be broken, so every
# test here follows the logout with a real authenticated request.


LOGOUT_URL = "/api/auth/logout/"
ME_URL = "/api/auth/me/"


def token_for(client, username="rania", password="a-strong-passw0rd!"):
    """Register a user and return a client already carrying their token."""
    register(client, username=username, email=f"{username}@example.com", password=password)
    response = client.post(LOGIN_URL, {"username": username, "password": password}, format="json")
    return response.json()["token"]


def test_logout_returns_204_and_deletes_the_token(client):
    token = token_for(client)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    response = client.post(LOGOUT_URL)

    assert response.status_code == 204
    assert not Token.objects.filter(key=token).exists()


def test_the_revoked_token_stops_working(client):
    token = token_for(client)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    assert client.get(ME_URL).status_code == 200

    client.post(LOGOUT_URL)

    assert client.get(ME_URL).status_code == 401


def test_logout_without_a_token_returns_401(client):
    response = client.post(LOGOUT_URL)

    assert response.status_code == 401


def test_logging_out_twice_returns_401_the_second_time(client):
    token = token_for(client)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    first = client.post(LOGOUT_URL)
    second = client.post(LOGOUT_URL)

    assert first.status_code == 204
    assert second.status_code == 401


def test_logging_out_does_not_revoke_another_users_token(client):
    other_client = APIClient()
    other_token = token_for(other_client, username="davis")
    token = token_for(client)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    client.post(LOGOUT_URL)

    assert Token.objects.filter(key=other_token).exists()
    other_client.credentials(HTTP_AUTHORIZATION=f"Token {other_token}")
    assert other_client.get(ME_URL).status_code == 200


def test_logging_back_in_after_logout_issues_a_working_token(client):
    old_token = token_for(client)
    client.credentials(HTTP_AUTHORIZATION=f"Token {old_token}")
    client.post(LOGOUT_URL)

    response = client.post(
        LOGIN_URL, {"username": "rania", "password": "a-strong-passw0rd!"}, format="json"
    )

    assert response.status_code == 200
    new_token = response.json()["token"]
    assert new_token != old_token
    client.credentials(HTTP_AUTHORIZATION=f"Token {new_token}")
    assert client.get(ME_URL).status_code == 200


# --- current user -----------------------------------------------------------------------


def test_current_user_returns_the_token_owner(client):
    token = token_for(client)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    response = client.get(ME_URL)

    assert response.status_code == 200
    assert response.json() == {"username": "rania", "email": "rania@example.com"}


def test_current_user_without_a_token_returns_401(client):
    response = client.get(ME_URL)

    assert response.status_code == 401


def test_current_user_with_a_garbage_token_returns_401(client):
    client.credentials(HTTP_AUTHORIZATION="Token not-a-real-token")

    response = client.get(ME_URL)

    assert response.status_code == 401


def test_each_token_resolves_to_its_own_user(client):
    rania_token = token_for(client, username="rania")
    davis_client = APIClient()
    davis_token = token_for(davis_client, username="davis")

    client.credentials(HTTP_AUTHORIZATION=f"Token {rania_token}")
    davis_client.credentials(HTTP_AUTHORIZATION=f"Token {davis_token}")

    assert client.get(ME_URL).json()["username"] == "rania"
    assert davis_client.get(ME_URL).json()["username"] == "davis"
