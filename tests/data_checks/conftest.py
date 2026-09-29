"""
Data coherence checks run against the database DATABASE_URL points at, as it is.

The unit suite gets a fresh, empty test database from pytest-django, which is right for
testing code and useless for testing data. These checks override django_db_setup so no
test database is created and the queries see whatever was seeded or ingested. They only
read; every test still runs inside a transaction that pytest-django rolls back.

Run them on their own, from the repo root:

    pytest -m data
"""

import pytest
from django.db import connection


@pytest.fixture(scope="session")
def django_db_setup():
    """Use the configured database instead of creating an empty test_ copy."""


@pytest.fixture(autouse=True)
def _real_database_only():
    # If the unit suite ran first in the same session, pytest-django has already pointed
    # the connection at its throwaway test_ database, and every check below would pass or
    # fail against data nobody seeded.
    name = connection.settings_dict["NAME"]
    if name.startswith("test_"):
        pytest.fail(
            f"Data checks are pointed at the throwaway test database '{name}', not your "
            "real one. Run them on their own: `pytest -m data`."
        )
