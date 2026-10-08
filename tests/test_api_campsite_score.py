"""
Tests for the score on the campsite detail endpoint (TM05-45).

The request must score from stored values only. Setup fills the stores the way the real
system does -- enrich() fills the terrain cache, a forecast run fills the weather cache --
from stubs. Then the network is closed: 3DEP, Open-Meteo and every requests call raise
and are recorded, so each test proves the request made no live call.
"""

import copy
import json
from pathlib import Path

import pytest
import requests
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon
from rest_framework.test import APIClient

from analysis.analyses import elevation, weather
from analysis.analyses.weather import WeatherForecast
from analysis.models import AnalysisResult
from enrichment.facts import enrich
from geodata.models import Campsite, PublicLand, Trail, WaterFeature
from scoring.config import load, parse

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

LON, LAT = -73.85, 44.18
M_PER_DEG_LAT = 111_120
FORECAST = json.loads((Path(__file__).parent / "fixtures" / "open_meteo_forecast.json").read_text())


class Network:
    """Stands in for 3DEP, Open-Meteo and requests. Open while a test fills the stores;
    once closed, every call is recorded and fails."""

    def __init__(self):
        self.open = True
        self.calls = []

    def guard(self, name):
        if not self.open:
            self.calls.append(name)
            raise AssertionError(f"live {name} call during a stored-values-only request")

    def post_samples(self, points):
        self.guard("3DEP")
        return {
            "samples": [
                {"locationId": i, "value": "500", "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        }

    def fetch_json(self, url, params):
        self.guard("Open-Meteo")
        return copy.deepcopy(FORECAST)

    def request(self, *args, **kwargs):
        self.calls.append("requests")
        raise AssertionError("no test here may reach the network")


@pytest.fixture(autouse=True)
def network(monkeypatch):
    stub = Network()
    monkeypatch.setattr(elevation, "post_samples", stub.post_samples)
    monkeypatch.setattr(weather, "fetch_json", stub.fetch_json)
    monkeypatch.setattr(requests.Session, "request", stub.request)
    return stub


def north(metres):
    return Point(LON, LAT + metres / M_PER_DEG_LAT, srid=4326)


def surroundings():
    """Water 60 m north, a trail 60 m south, open GAP 1 land around the site."""
    WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id="w1",
        name="Test Brook",
        geom=north(60),
        feature_type="stream",
        perennial=True,
    )
    lat = LAT - 60 / M_PER_DEG_LAT
    Trail.objects.create(
        source=Trail.Source.OSM,
        source_id="t1",
        name="Test Trail",
        geom=MultiLineString(LineString((LON - 0.01, lat), (LON + 0.01, lat)), srid=4326),
    )
    ring = Polygon.from_bbox((LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01))
    ring.srid = 4326
    PublicLand.objects.create(
        source=PublicLand.Source.PADUS,
        source_id="p1",
        geom=MultiPolygon(ring, srid=4326),
        public_access="open",
        gap_status="1",
        designation="Test Wilderness",
    )


def campsite(source_id="node/1"):
    return Campsite.objects.create(
        source=Campsite.Source.OSM,
        source_id=source_id,
        name="Test Site",
        geom=Point(LON, LAT, srid=4326),
        raw={"type": "node", "tags": {"tourism": "camp_site"}},
    )


def detail(source_id):
    return APIClient().get(f"/api/campsites/{source_id}/detail/")


def factor(body, key):
    return next(f for f in body["score_breakdown"]["factors"] if f["key"] == key)


def test_enriched_site_is_scored_from_stored_values(network):
    surroundings()
    site = campsite()
    enrich(site)  # fills the terrain cache, as enrich_campsites does
    WeatherForecast().run(site.geom, {"days": load().factor("weather")["forecast_days"]})
    network.open = False

    response = detail("node/1")

    assert response.status_code == 200
    body = response.json()
    assert body["score_status"] == "scored"
    result = body["score_breakdown"]
    assert body["score"] == result["score"]
    assert isinstance(body["score"], int) and 0 <= body["score"] <= 100
    assert set(result) == {
        "contract",
        "model_version",
        "config_digest",
        "location",
        "score",
        "factors",
        "caps",
        "suitability_score",
        "legal_status",
    }
    assert result["contract"] == 1
    assert [f["key"] for f in result["factors"]] == list(load().weights)
    for entry in result["factors"]:
        assert set(entry) == {
            "key",
            "label",
            "status",
            "score",
            "weight",
            "effective_weight",
            "contribution",
            "measurement",
            "explanation",
        }
    for key in ("water", "trail", "legal", "slope", "weather"):
        assert factor(body, key)["status"] == "scored"
    assert factor(body, "slope")["measurement"]["cached"] is True
    assert factor(body, "weather")["measurement"]["cached"] is True
    assert network.calls == []


def test_missing_stored_inputs_are_not_available_and_never_fetched(network):
    surroundings()
    site = campsite()
    enrich(site)
    # Neither cache holds an answer for this site any more, so a live fetch is the only
    # way to get one -- which the request must not make.
    AnalysisResult.objects.all().delete()
    network.open = False

    body = detail("node/1").json()

    assert body["score_status"] == "scored"
    for key in ("slope", "weather"):
        entry = factor(body, key)
        assert entry["status"] == "not_available"
        assert entry["score"] is None
        assert entry["effective_weight"] == 0
    assert factor(body, "water")["status"] == "scored"
    assert network.calls == []


def test_enriched_site_with_nothing_stored_to_score_is_null_not_an_error(network, monkeypatch):
    shipped = load()
    only_live = parse(
        {
            "model_version": "test",
            "weights": {"weather": 1, "slope": 1},
            "factors": copy.deepcopy(shipped.factors),
        }
    )
    monkeypatch.setattr("scoring.engine.load", lambda: only_live)
    enrich(campsite())
    AnalysisResult.objects.all().delete()
    network.open = False

    response = detail("node/1")

    assert response.status_code == 200
    body = response.json()
    assert body["score"] is None
    assert body["score_status"] == "not_available"
    assert body["score_breakdown"] is None
    assert network.calls == []


def test_unenriched_site_has_a_null_score_with_a_status(network):
    surroundings()
    campsite("campsite/104324")
    network.open = False

    response = detail("campsite/104324")

    assert response.status_code == 200
    body = response.json()
    assert body["facts"] is None
    assert body["score"] is None
    assert body["score_status"] == "pending"
    assert body["score_breakdown"] is None
    assert network.calls == []


def test_unknown_campsite_is_404(network):
    network.open = False
    assert detail("node/0").status_code == 404
    assert network.calls == []
