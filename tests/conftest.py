"""
Shared pytest fixtures available to every test in the repo.
Add fixtures here rather than duplicating setup across test files.
"""

import os

import pytest


@pytest.fixture(scope="session")
def project_root():
    """Absolute path to the repo root."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def env(monkeypatch):
    """Set environment variables for a single test without leaking into others.

    Usage:
        def test_something(env):
            env({"DATABASE_URL": "postgres://localhost/test"})
    """

    def _set(values: dict):
        for key, value in values.items():
            monkeypatch.setenv(key, value)

    return _set


@pytest.fixture
def sample_bbox():
    """A small bounding box (Syracuse NY area) for geo-related tests."""
    return {"min_lon": -76.2, "min_lat": 43.0, "max_lon": -76.1, "max_lat": 43.1}


@pytest.fixture
def clean_registry():
    """Isolate the adapter registry so a test can register a throwaway adapter.

    Snapshots the registry, empties it, and restores it afterwards. Without this a test
    adapter would leak into every later test's --list-sources output.
    """
    from pipeline.adapters import registry

    saved = registry.snapshot()
    registry.restore({})
    try:
        yield registry
    finally:
        registry.restore(saved)
