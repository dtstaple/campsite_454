"""
Weather forecast from Open-Meteo, the first analysis (TM05-44).

Source, verified live 2026-10-02 (HTTP 200, ~0.8 s, no key):

    GET https://api.open-meteo.com/v1/forecast
        ?latitude=44.175&longitude=-73.975
        &current=temperature_2m,precipitation,wind_speed_10m,wind_gusts_10m,weather_code
        &daily=temperature_2m_min,temperature_2m_max,precipitation_sum,
               precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max
        &forecast_days=3&timezone=auto

Response shape (recorded in tests/fixtures/open_meteo_forecast.json):

    {"latitude": 44.182407, "longitude": -73.969986, "elevation": 803.0,
     "timezone": "America/New_York", "generationtime_ms": 2.6,
     "current_units": {...}, "current": {"time": "2026-10-02T16:15", "interval": 900,
         "temperature_2m": 12.3, "precipitation": 0.1, "wind_speed_10m": 13.4,
         "wind_gusts_10m": 32.8, "weather_code": 51},
     "daily_units": {...}, "daily": {"time": ["2026-10-02", ...],
         "temperature_2m_min": [...], "temperature_2m_max": [...],
         "precipitation_sum": [...], "precipitation_probability_max": [...],
         "wind_speed_10m_max": [...], "wind_gusts_10m_max": [...]}}

Units: °C, mm, km/h, %. The API answers for its own model grid cell (the returned
latitude/longitude), not the exact point -- 44.175,-73.975 and 44.18,-73.95 both came back
as 44.1824,-73.9700 -- which is why requests are snapped to a 0.05° grid before keying.

Cached for one hour: Open-Meteo refreshes its models hourly, and a forecast older than
that is stale. Expired rows are purged, so this is a short cache, not a weather archive.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import requests
from django.contrib.gis.geos import GEOSGeometry

from analysis.base import Analysis, AnalysisError, Computed, Window
from pipeline.retry import call_with_backoff

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
CURRENT = ["temperature_2m", "precipitation", "wind_speed_10m", "wind_gusts_10m", "weather_code"]
DAILY = [
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
]
TIMEOUT_SECONDS = 5


def fetch_json(url: str, params: dict) -> dict:
    """One GET, one quick retry. Weather is on the scoring path, so failing fast and
    letting the factor report not_available beats making a user wait through backoff."""

    def attempt():
        response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()

    return call_with_backoff(
        attempt,
        retry_on=(requests.RequestException, ValueError),
        on_exhausted=lambda error: AnalysisError(f"Open-Meteo request failed: {error}"),
        max_attempts=2,
        backoff_seconds=0.5,
        describe="Open-Meteo forecast",
    )


class WeatherForecast(Analysis):
    name = "weather"
    version = "1"
    ttl = timedelta(hours=1)
    grid_degrees = 0.05

    def window_for(self, now: datetime, params: dict) -> Window:
        """The forecast as issued for this hour, covering `days` days from it."""
        start = now.replace(minute=0, second=0, microsecond=0)
        return Window(start, start + timedelta(days=params.get("days", 3)))

    def compute(self, geom: GEOSGeometry, window: Window | None, params: dict) -> Computed:
        days = params.get("days", 3)
        request = {
            "latitude": geom.y,
            "longitude": geom.x,
            "current": ",".join(CURRENT),
            "daily": ",".join(DAILY),
            "forecast_days": days,
            "timezone": "auto",
        }
        payload = fetch_json(OPEN_METEO_URL, request)
        value = parse_forecast(payload)
        provenance = {
            "source": "open-meteo",
            "url": OPEN_METEO_URL,
            "request": request,
            "response_grid": value["grid"],
            "generationtime_ms": payload.get("generationtime_ms"),
            "current_time": value["current"]["time"],
        }
        return Computed(value, provenance)


def parse_forecast(payload: dict) -> dict:
    """Reduce an Open-Meteo response to the answer we keep. Raises AnalysisError if the
    shape is not what was verified, rather than caching something half-understood."""
    try:
        current = payload["current"]
        daily = payload["daily"]
        dates = daily["time"]
        rows = [
            {
                "date": date,
                "temperature_min_c": daily["temperature_2m_min"][i],
                "temperature_max_c": daily["temperature_2m_max"][i],
                "precipitation_mm": daily["precipitation_sum"][i],
                "precipitation_probability_pct": daily["precipitation_probability_max"][i],
                "wind_max_kmh": daily["wind_speed_10m_max"][i],
                "gust_max_kmh": daily["wind_gusts_10m_max"][i],
            }
            for i, date in enumerate(dates)
        ]
        return {
            "grid": {
                "lat": payload["latitude"],
                "lon": payload["longitude"],
                "elevation_m": payload.get("elevation"),
            },
            "timezone": payload.get("timezone"),
            "current": {
                "time": current["time"],
                "temperature_c": current["temperature_2m"],
                "precipitation_mm": current["precipitation"],
                "wind_kmh": current["wind_speed_10m"],
                "gust_kmh": current["wind_gusts_10m"],
                "weather_code": current["weather_code"],
            },
            "daily": rows,
        }
    except (KeyError, IndexError, TypeError) as error:
        raise AnalysisError(f"unexpected Open-Meteo response shape: {error!r}") from error
