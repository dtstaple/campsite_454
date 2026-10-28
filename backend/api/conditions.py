"""
GET /api/conditions/?lat=&lon= -- the short forecast and active weather alerts for a
point, for the Conditions section of the trail and campsite panels (TM05-120).

Both come through the analysis cache (TM05-44): the Open-Meteo forecast for an hour (the
same entry the weather factor scores from), the NWS alerts for five minutes. Neither is
stored beyond that. Each section carries its own status, source and fetch time, so one
upstream failing still shows the other, and the panel can say which one is down.
Contract: docs/api.md, "Conditions".
"""

import math

from django.contrib.gis.geos import Point
from rest_framework.decorators import api_view
from rest_framework.response import Response

from analysis.analyses.alerts import NWS_ALERTS_URL, WeatherAlerts
from analysis.analyses.weather import OPEN_METEO_URL, WeatherForecast
from analysis.base import AnalysisError

FORECAST_DAYS = 3
OK = "ok"
ERROR = "error"

FORECAST_SOURCE = {"source": "Open-Meteo", "source_url": OPEN_METEO_URL}
ALERTS_SOURCE = {"source": "US National Weather Service", "source_url": NWS_ALERTS_URL}


def _coordinate(request, name: str, limit: float) -> float:
    raw = request.query_params.get(name)
    if raw is None:
        raise ValueError(f"{name} is required")
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(value) or abs(value) > limit:
        raise ValueError(f"{name} must be between -{limit:g} and {limit:g}")
    return value


def _fetched(outcome) -> dict:
    return {
        "status": OK,
        "fetched_at": outcome.computed_at.isoformat(),
        "expires_at": outcome.expires_at.isoformat(),
        "cached": outcome.cached,
    }


def forecast_section(point: Point) -> dict:
    try:
        outcome = WeatherForecast().run(point, {"days": FORECAST_DAYS})
    except AnalysisError:
        return {**FORECAST_SOURCE, "status": ERROR, "message": "Forecast unavailable right now."}
    value = outcome.value
    return {
        **FORECAST_SOURCE,
        **_fetched(outcome),
        "timezone": value.get("timezone"),
        "days": value["daily"][:FORECAST_DAYS],
    }


def alerts_section(point: Point) -> dict:
    try:
        outcome = WeatherAlerts().run(point)
    except AnalysisError:
        return {
            **ALERTS_SOURCE,
            "status": ERROR,
            "message": "Weather alerts unavailable right now.",
        }
    return {**ALERTS_SOURCE, **_fetched(outcome), "items": outcome.value["alerts"]}


@api_view(["GET"])
def conditions_view(request):
    try:
        lat = _coordinate(request, "lat", 90)
        lon = _coordinate(request, "lon", 180)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)
    point = Point(lon, lat, srid=4326)
    return Response(
        {
            "location": {"lat": lat, "lon": lon},
            "forecast": forecast_section(point),
            "alerts": alerts_section(point),
        }
    )
