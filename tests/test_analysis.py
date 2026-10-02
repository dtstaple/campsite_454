"""
Tests for the analysis and cache layer (TM05-44).

Covers the AC directly: cache key generation, the hit and miss paths, expiry, and
provenance, using a throwaway analysis so the framework is tested apart from any source;
then the weather analysis against a recorded Open-Meteo response. Nothing touches the
network.
"""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.contrib.gis.geos import LineString, Point

from analysis.analyses.weather import WeatherForecast, parse_forecast
from analysis.base import (
    Analysis,
    AnalysisError,
    Computed,
    Window,
    cache_key,
    canonical_geom,
    quantize,
)
from analysis.models import AnalysisResult

NOW = datetime(2026, 10, 2, 16, 20, tzinfo=UTC)
POINT = Point(-73.95, 44.18, srid=4326)
FORECAST = json.loads((Path(__file__).parent / "fixtures" / "open_meteo_forecast.json").read_text())


class Counting(Analysis):
    """A throwaway analysis that counts how often it actually computes."""

    name = "counting"
    version = "1"
    ttl = timedelta(minutes=30)
    grid_degrees = 0.05

    def __init__(self):
        self.calls = 0

    def window_for(self, now, params):
        start = now.replace(minute=0, second=0, microsecond=0)
        return Window(start, start + timedelta(hours=1))

    def compute(self, geom, window, params):
        self.calls += 1
        return Computed({"answer": self.calls}, {"source": "test"})


def key(**overrides):
    parts = {
        "name": "a",
        "version": "1",
        "geom": canonical_geom(POINT),
        "window": Window(NOW, NOW + timedelta(hours=1)),
        "params": {"days": 3},
    }
    parts.update(overrides)
    return cache_key(
        parts["name"], parts["version"], parts["geom"], parts["window"], parts["params"]
    )


# --- cache key generation (no database) ---------------------------------------------


class TestCacheKey:
    def test_is_stable(self):
        assert key() == key()
        assert len(key()) == 64

    @pytest.mark.parametrize(
        "override",
        [
            {"name": "b"},
            {"version": "2"},
            {"geom": canonical_geom(Point(-73.90, 44.18, srid=4326))},
            {"window": Window(NOW + timedelta(hours=1), NOW + timedelta(hours=2))},
            {"window": None},
            {"params": {"days": 7}},
        ],
    )
    def test_changes_with_every_component(self, override):
        assert key(**override) != key()

    def test_parameter_order_does_not_matter(self):
        assert key(params={"a": 1, "b": 2}) == key(params={"b": 2, "a": 1})

    def test_float_noise_does_not_split_entries(self):
        noisy = Point(-73.95 + 1e-9, 44.18 - 1e-9, srid=4326)
        assert key(geom=canonical_geom(noisy)) == key()

    def test_points_in_one_grid_cell_share_a_key(self):
        a = canonical_geom(quantize(Point(-73.951, 44.181, srid=4326), 0.05))
        b = canonical_geom(quantize(Point(-73.999, 44.199, srid=4326), 0.05))
        c = canonical_geom(quantize(Point(-73.949, 44.181, srid=4326), 0.05))
        assert key(geom=a) == key(geom=b)
        assert key(geom=a) != key(geom=c)

    def test_lines_are_not_snapped(self):
        line = LineString((-73.951, 44.181), (-73.952, 44.182), srid=4326)
        assert quantize(line, 0.05) is line

    def test_other_srids_are_keyed_in_4326(self):
        projected = POINT.transform(5070, clone=True)
        assert key(geom=canonical_geom(projected)) == key()


# --- hit, miss, expiry, provenance (database) ---------------------------------------


@pytest.mark.django_db
@pytest.mark.integration
class TestRun:
    def test_miss_computes_and_stores_with_provenance(self):
        analysis = Counting()
        outcome = analysis.run(POINT, {"days": 3}, now=NOW)

        assert outcome.cached is False
        assert analysis.calls == 1
        row = AnalysisResult.objects.get(key=outcome.key)
        assert row.value == {"answer": 1}
        assert row.expires_at == NOW + timedelta(minutes=30)
        assert row.window_start == NOW.replace(minute=0)
        assert row.provenance["source"] == "test"
        assert row.provenance["analysis"] == "counting"
        assert row.provenance["version"] == "1"
        assert row.provenance["params"] == {"days": 3}
        assert row.provenance["computed_at"] == NOW.isoformat()

    def test_repeat_request_is_served_from_cache(self):
        analysis = Counting()
        first = analysis.run(POINT, {"days": 3}, now=NOW)
        second = analysis.run(POINT, {"days": 3}, now=NOW + timedelta(minutes=5))

        assert second.cached is True
        assert second.value == first.value
        assert analysis.calls == 1

    def test_nearby_point_in_the_same_cell_is_a_hit(self):
        analysis = Counting()
        analysis.run(Point(-73.951, 44.181, srid=4326), now=NOW)
        assert analysis.run(Point(-73.999, 44.199, srid=4326), now=NOW).cached is True

    def test_expired_entry_is_recomputed_and_replaced(self):
        analysis = Counting()
        first = analysis.run(POINT, now=NOW)
        # Same hour, so the same window and key, but past the 30 minute TTL.
        later = NOW + timedelta(minutes=31)
        assert later.hour == NOW.hour
        second = analysis.run(POINT, now=later)

        assert second.cached is False
        assert second.key == first.key
        assert analysis.calls == 2
        assert AnalysisResult.objects.filter(key=first.key).count() == 1
        assert AnalysisResult.objects.get(key=first.key).value == {"answer": 2}

    def test_expired_entries_are_purged(self):
        analysis = Counting()
        analysis.run(POINT, now=NOW)
        analysis.run(Point(-70.0, 44.0, srid=4326), now=NOW + timedelta(hours=2))
        assert AnalysisResult.objects.filter(analysis="counting").count() == 1

    def test_version_bump_invalidates(self):
        analysis = Counting()
        analysis.run(POINT, now=NOW)
        analysis.version = "2"
        assert analysis.run(POINT, now=NOW).cached is False

    def test_failed_compute_caches_nothing(self):
        class Broken(Counting):
            name = "broken"

            def compute(self, geom, window, params):
                raise AnalysisError("source down")

        with pytest.raises(AnalysisError):
            Broken().run(POINT, now=NOW)
        assert not AnalysisResult.objects.filter(analysis="broken").exists()


# --- weather ------------------------------------------------------------------------


class TestWeatherParsing:
    def test_reduces_the_recorded_response(self):
        value = parse_forecast(FORECAST)
        assert value["grid"]["lat"] == FORECAST["latitude"]
        assert value["current"]["temperature_c"] == FORECAST["current"]["temperature_2m"]
        assert len(value["daily"]) == 3
        day = value["daily"][0]
        assert day["date"] == FORECAST["daily"]["time"][0]
        assert day["precipitation_mm"] == FORECAST["daily"]["precipitation_sum"][0]
        assert set(day) == {
            "date",
            "temperature_min_c",
            "temperature_max_c",
            "precipitation_mm",
            "precipitation_probability_pct",
            "wind_max_kmh",
            "gust_max_kmh",
        }

    def test_unexpected_shape_is_an_error_not_a_cache_entry(self):
        broken = copy.deepcopy(FORECAST)
        del broken["daily"]["precipitation_sum"]
        with pytest.raises(AnalysisError):
            parse_forecast(broken)

    def test_window_is_the_issuing_hour_plus_forecast_days(self):
        window = WeatherForecast().window_for(NOW, {"days": 3})
        assert window.start == datetime(2026, 10, 2, 16, tzinfo=UTC)
        assert window.end == window.start + timedelta(days=3)


@pytest.mark.django_db
@pytest.mark.integration
class TestWeatherRun:
    def test_requests_the_verified_endpoint_and_records_provenance(self, monkeypatch):
        seen = []

        def fake_fetch(url, params):
            seen.append((url, params))
            return copy.deepcopy(FORECAST)

        monkeypatch.setattr("analysis.analyses.weather.fetch_json", fake_fetch)
        outcome = WeatherForecast().run(POINT, {"days": 3}, now=NOW)

        url, params = seen[0]
        assert url == "https://api.open-meteo.com/v1/forecast"
        assert params["forecast_days"] == 3
        assert "precipitation_sum" in params["daily"]
        # Requested for the centre of the 0.05 degree cell, not the raw point.
        assert (params["longitude"], params["latitude"]) == (-73.925, 44.175)
        assert outcome.provenance["source"] == "open-meteo"
        assert outcome.provenance["response_grid"]["lat"] == FORECAST["latitude"]
        assert AnalysisResult.objects.get(key=outcome.key).expires_at == NOW + timedelta(hours=1)

    def test_http_failure_becomes_analysis_error(self, monkeypatch):
        import requests

        from analysis.analyses import weather

        def fail(*args, **kwargs):
            raise requests.ConnectionError("no route")

        monkeypatch.setattr(weather.requests, "get", fail)
        with pytest.raises(AnalysisError):
            weather.fetch_json(weather.OPEN_METEO_URL, {})
