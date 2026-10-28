"""
Tests for GET /api/conditions/ (TM05-120): the forecast, an active alert, no alerts, and
an upstream failure of either source, plus the short cache. Open-Meteo and NWS are
replaced by recorded responses; nothing touches the network.
"""

import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
import requests
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.test import APIClient

from analysis.analyses import alerts, weather
from analysis.base import AnalysisError
from analysis.models import AnalysisResult

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

FIXTURES = Path(__file__).parent / "fixtures"
FORECAST = json.loads((FIXTURES / "open_meteo_forecast.json").read_text())
ALERTS = json.loads((FIXTURES / "nws_alerts_active.json").read_text())
NO_ALERTS = {**ALERTS, "features": []}
URL = "/api/conditions/"
HERE = {"lat": "44.18", "lon": "-73.95"}


class Upstream:
    """Stands in for both sources: records calls, answers from fixtures or fails."""

    def __init__(self, forecast=FORECAST, alerts_payload=ALERTS):
        self.forecast = forecast
        self.alerts = alerts_payload
        self.calls = {"forecast": [], "alerts": []}

    def fetch_forecast(self, url, params):
        self.calls["forecast"].append(params)
        if self.forecast is None:
            raise AnalysisError("Open-Meteo request failed: 503")
        return copy.deepcopy(self.forecast)

    def fetch_alerts(self, url, params):
        self.calls["alerts"].append(params)
        if self.alerts is None:
            raise AnalysisError("NWS alerts request failed: 503")
        return copy.deepcopy(self.alerts)


@pytest.fixture
def upstream(monkeypatch):
    fake = Upstream()
    monkeypatch.setattr(weather, "fetch_json", fake.fetch_forecast)
    monkeypatch.setattr(alerts, "fetch_json", fake.fetch_alerts)
    return fake


@pytest.fixture
def client():
    return APIClient()


def test_forecast_has_three_days_with_source_and_fetch_time(client, upstream):
    body = client.get(URL, HERE).json()

    forecast = body["forecast"]
    assert forecast["status"] == "ok"
    assert forecast["source"] == "Open-Meteo"
    assert forecast["source_url"] == weather.OPEN_METEO_URL
    assert forecast["fetched_at"] and forecast["expires_at"]
    assert forecast["cached"] is False
    assert [day["date"] for day in forecast["days"]] == FORECAST["daily"]["time"]
    first = forecast["days"][0]
    assert first["temperature_max_c"] == FORECAST["daily"]["temperature_2m_max"][0]
    assert first["precipitation_probability_pct"] is not None
    assert body["location"] == {"lat": 44.18, "lon": -73.95}


def test_active_alerts_are_listed_most_severe_first_with_source(client, upstream):
    section = client.get(URL, HERE).json()["alerts"]

    assert section["status"] == "ok"
    assert section["source"] == "US National Weather Service"
    assert section["fetched_at"]
    events = [item["event"] for item in section["items"]]
    assert events == ["Special Weather Statement", "Frost Advisory"]
    top = section["items"][0]
    assert top["severity"] == "Moderate"
    assert top["sender_name"] == "NWS Midland/Odessa TX"
    assert top["expires"] == "2026-10-27T20:00:00-05:00"
    assert top["instruction"].startswith("If outdoors")


def test_no_alerts_is_ok_with_an_empty_list(client, upstream):
    upstream.alerts = NO_ALERTS
    section = client.get(URL, HERE).json()["alerts"]
    assert section["status"] == "ok"
    assert section["items"] == []


def test_forecast_failure_still_returns_alerts(client, upstream):
    upstream.forecast = None
    response = client.get(URL, HERE)

    assert response.status_code == 200
    body = response.json()
    assert body["forecast"]["status"] == "error"
    assert body["forecast"]["source"] == "Open-Meteo"
    assert body["forecast"]["message"]
    assert "days" not in body["forecast"]
    assert body["alerts"]["status"] == "ok"


def test_alerts_failure_still_returns_forecast(client, upstream):
    upstream.alerts = None
    body = client.get(URL, HERE).json()
    assert body["alerts"]["status"] == "error"
    assert body["alerts"]["message"]
    assert "items" not in body["alerts"]
    assert body["forecast"]["status"] == "ok"


def test_failures_are_not_cached(client, upstream):
    upstream.forecast = None
    upstream.alerts = None
    client.get(URL, HERE)
    assert not AnalysisResult.objects.exists()

    upstream.forecast = FORECAST
    upstream.alerts = ALERTS
    body = client.get(URL, HERE).json()
    assert body["forecast"]["status"] == "ok"
    assert body["alerts"]["status"] == "ok"


def test_second_request_is_served_from_the_short_cache(client, upstream):
    client.get(URL, HERE)
    body = client.get(URL, HERE).json()

    assert len(upstream.calls["forecast"]) == 1
    assert len(upstream.calls["alerts"]) == 1
    assert body["forecast"]["cached"] is True
    assert body["alerts"]["cached"] is True


def test_answers_expire_briefly_and_are_purged(client, upstream):
    client.get(URL, HERE)
    alert_row = AnalysisResult.objects.get(analysis="weather-alerts")
    forecast_row = AnalysisResult.objects.get(analysis="weather")
    assert alert_row.expires_at - alert_row.computed_at == timedelta(minutes=5)
    assert forecast_row.expires_at - forecast_row.computed_at == timedelta(hours=1)

    # Two hours on, both are past their TTL: an alert lookup refetches, and the expired
    # rows are purged rather than kept as history.
    later = timezone.now() + timedelta(hours=2)
    outcome = alerts.WeatherAlerts().run(alert_row.geom, now=later)
    assert outcome.cached is False
    assert len(upstream.calls["alerts"]) == 2
    assert weather.WeatherForecast().purge_expired(later) == 1
    assert not AnalysisResult.objects.filter(analysis="weather").exists()


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"lat": "44.18"},
        {"lat": "abc", "lon": "-73.95"},
        {"lat": "91", "lon": "-73.95"},
        {"lat": "44.18", "lon": "-181"},
        {"lat": "nan", "lon": "-73.95"},
    ],
)
def test_bad_coordinates_are_400(client, upstream, params):
    response = client.get(URL, params)
    assert response.status_code == 400
    assert "error" in response.json()
    assert upstream.calls == {"forecast": [], "alerts": []}


def test_alerts_request_sends_user_agent_and_a_four_decimal_point(monkeypatch):
    seen = {}

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return copy.deepcopy(NO_ALERTS)

    def fake_get(url, params, headers, timeout):
        seen.update(url=url, params=params, headers=headers)
        return Reply()

    monkeypatch.setattr(alerts.requests, "get", fake_get)
    outcome = alerts.WeatherAlerts().run(Point(-73.95123, 44.18456, srid=4326))

    assert seen["url"] == "https://api.weather.gov/alerts/active"
    assert seen["headers"]["User-Agent"].startswith("CampSite-CIS454")
    lat, lon = seen["params"]["point"].split(",")
    assert len(lat.split(".")[1]) == 4 and len(lon.split(".")[1]) == 4
    assert outcome.provenance["source"] == "nws"
    assert outcome.value["alerts"] == []


def test_alerts_http_failure_becomes_analysis_error(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.HTTPError("400 Client Error: out of bounds")

    monkeypatch.setattr(alerts.requests, "get", fail)
    with pytest.raises(AnalysisError):
        alerts.fetch_json(alerts.NWS_ALERTS_URL, {"point": "46.0000,8.9000"})


def test_unexpected_alerts_shape_is_an_analysis_error():
    with pytest.raises(AnalysisError):
        alerts.parse_alerts({"features": [{"no": "properties"}]})
