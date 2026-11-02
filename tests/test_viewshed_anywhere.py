"""
Viewshed from any point on the map (TM05-151): the endpoint, its cache per rounded
location and radius, its errors, and the bare-earth labelling. GeoLibre itself is stubbed
here; test_terrain.py covers the viewshed tool chain the endpoint shares with campsites.
"""

from pathlib import Path

import pytest
from rest_framework.test import APIClient

from analysis.analyses import viewshed
from analysis.models import AnalysisResult
from api.viewshed import LABEL, summary
from terrain import runtime, worker
from terrain.payload import NOTE

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

# Inside the Adirondacks box in regions.yml, away from any grid-cell edge.
LAT, LON = 44.15020, -73.95020


class FakeViewshed:
    """Stands in for worker.viewshed_at and records each call."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, wasm, src, srid, nodata, x, y, **kwargs):
        self.calls.append({"x": x, "y": y, **kwargs})
        if self.fail:
            raise runtime.ToolFailed("no station points intersect valid DEM cells")
        d = 0.01
        square = [[LON - d, LAT - d], [LON + d, LAT - d], [LON + d, LAT + d], [LON - d, LAT + d]]
        polygon = {"type": "Polygon", "coordinates": [[*square, square[0]]]}
        return {"area_km2": 7.123, "direction": "east", "polygons": [polygon]}, 1


@pytest.fixture
def fake(monkeypatch):
    stub = FakeViewshed()
    monkeypatch.setattr(worker, "viewshed_at", stub)
    monkeypatch.setattr(
        viewshed,
        "inputs",
        lambda region, registry: (
            Path("fake.wasm"),
            Path("fake.tif"),
            True,
            {"source": "test", "dem_digest": "abc"},
        ),
    )
    return stub


def get(client, **params):
    return client.get("/api/viewshed/", params)


@pytest.fixture
def client():
    return APIClient()


def test_any_point_gets_a_viewshed_feature_with_its_summary(client, fake):
    response = get(client, lat=LAT, lon=LON)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["type"] == "Feature"
    assert body["geometry"]["type"] == "MultiPolygon"
    props = body["properties"]
    assert props["region"] == "adirondacks"
    assert props["area_km2"] == 7.123
    assert props["direction"] == "east"
    assert props["radius_m"] == 10000  # the campsite viewshed's own radius by default
    assert props["eye_height_m"] == 1.7
    assert props["summary"] == "About 7.1 km² visible within 10 km, mostly to the east."
    assert props["cached"] is False
    # The same tool settings as the campsite viewshed.
    assert fake.calls[0]["radius_m"] == 10000
    assert fake.calls[0]["resolution_m"] == 30
    assert fake.calls[0]["eye_height_m"] == 1.7


def test_it_is_labelled_bare_earth(client, fake):
    props = get(client, lat=LAT, lon=LON).json()["properties"]
    assert props["label"] == LABEL == "Bare-earth elevation"
    assert props["note"] == NOTE
    assert "Trees, buildings" in props["note"]


def test_presses_in_one_rounded_cell_share_an_answer(client, fake):
    first = get(client, lat=LAT, lon=LON).json()["properties"]
    again = get(client, lat=LAT + 0.0001, lon=LON - 0.0001).json()["properties"]
    assert len(fake.calls) == 1
    assert again["cached"] is True
    assert again["observer"] == first["observer"]
    assert AnalysisResult.objects.filter(analysis="point_viewshed").count() == 1


def test_the_cache_is_per_radius_rounded_to_a_kilometre(client, fake):
    get(client, lat=LAT, lon=LON, radius_m=5000)
    rounded = get(client, lat=LAT, lon=LON, radius_m=5200).json()["properties"]
    assert len(fake.calls) == 1 and rounded["cached"] is True
    assert rounded["radius_m"] == 5000

    get(client, lat=LAT, lon=LON, radius_m=3000)
    assert len(fake.calls) == 2
    # Capped at the pipeline's 10 km, so 50 km is the 10 km answer.
    capped = get(client, lat=LAT, lon=LON, radius_m=50000).json()["properties"]
    assert capped["radius_m"] == 10000
    assert len(fake.calls) == 3


def test_a_different_place_is_computed_afresh(client, fake):
    get(client, lat=LAT, lon=LON)
    get(client, lat=LAT + 0.01, lon=LON)
    assert len(fake.calls) == 2


@pytest.mark.parametrize(
    "params, message",
    [
        ({"lon": LON}, "lat is required"),
        ({"lat": 95, "lon": LON}, "lat must be between"),
        ({"lat": LAT, "lon": "east"}, "lon must be a number"),
        ({"lat": LAT, "lon": LON, "radius_m": "far"}, "radius_m must be a number"),
        ({"lat": LAT, "lon": LON, "radius_m": 0}, "radius_m must be greater than 0"),
    ],
)
def test_bad_parameters_are_400(client, fake, params, message):
    response = get(client, **params)
    assert response.status_code == 400
    assert message in response.json()["error"]
    assert fake.calls == []


def test_outside_every_region_is_422(client, fake):
    response = get(client, lat=39.7, lon=-105.0)
    assert response.status_code == 422
    assert "outside the areas" in response.json()["error"]


def test_off_the_elevation_model_is_422_and_not_cached(client, fake):
    fake.fail = True
    response = get(client, lat=LAT, lon=LON)
    assert response.status_code == 422
    assert "no elevation data" in response.json()["error"]
    assert not AnalysisResult.objects.filter(analysis="point_viewshed").exists()


def test_without_the_terrain_model_on_this_server_it_is_503(client, monkeypatch, tmp_path):
    monkeypatch.setenv("TERRAIN_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("GEOLIBRE_WASM", raising=False)
    response = get(client, lat=LAT, lon=LON)
    assert response.status_code == 503
    assert "terrain model hasn't been built" in response.json()["error"]


def test_summary_wording():
    assert summary(7.06, "all around", 10000) == (
        "About 7.1 km² visible within 10 km, in every direction."
    )
    assert summary(2.0, None, 5000) == "About 2.0 km² visible within 5 km."
    assert summary(0.01, None, 10000).startswith("Almost nothing visible within 10 km")
