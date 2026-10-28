"""
Active weather alerts from the US National Weather Service, for the Conditions panel
(TM05-120).

Source, verified live 2026-10-27 (no key; a descriptive User-Agent is required):

    GET https://api.weather.gov/alerts/active?point=44.175,-73.975
        User-Agent: CampSite-CIS454/0.1 (...)
        Accept: application/geo+json

Response shape (trimmed copy in tests/fixtures/nws_alerts_active.json):

    {"type": "FeatureCollection", "title": "Current watches, warnings, and advisories
     for 44.175 N, 73.975 W", "updated": "2026-10-28T00:12:06+00:00",
     "features": [{"properties": {"id": "urn:oid:...", "event": "Special Weather
         Statement", "headline": "...", "severity": "Moderate", "urgency": "Expected",
         "certainty": "Observed", "effective": "...", "onset": "...", "expires": "...",
         "ends": null, "senderName": "NWS Midland/Odessa TX", "areaDesc": "...",
         "description": "...", "instruction": "..."}}, ...]}

No alerts is an empty `features` list. A point outside NWS coverage (outside the US) is
HTTP 400 "out of bounds", which reaches the caller as an AnalysisError.

Cached for five minutes: a warning can be issued at any time, so an answer older than
that could hide one. Expired rows are purged, like the forecast -- a short cache, never a
record of past alerts.
"""

from __future__ import annotations

from datetime import timedelta

import requests
from django.contrib.gis.geos import GEOSGeometry

from analysis.base import Analysis, AnalysisError, Computed, Window
from pipeline.retry import call_with_backoff

NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"
USER_AGENT = "CampSite-CIS454/0.1 (Syracuse University student project; TM05)"
TIMEOUT_SECONDS = 5

#: Most severe first, the order the panel lists them in. NWS uses these CAP values.
SEVERITY_ORDER = ["Extreme", "Severe", "Moderate", "Minor", "Unknown"]


def fetch_json(url: str, params: dict) -> dict:
    """One GET, one quick retry, as for the forecast: the panel waits on this."""

    def attempt():
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    return call_with_backoff(
        attempt,
        retry_on=(requests.RequestException, ValueError),
        on_exhausted=lambda error: AnalysisError(f"NWS alerts request failed: {error}"),
        max_attempts=2,
        backoff_seconds=0.5,
        describe="NWS alerts",
    )


class WeatherAlerts(Analysis):
    name = "weather-alerts"
    version = "1"
    ttl = timedelta(minutes=5)
    # ~1 km: alerts are issued per county or forecast zone, so nearby clicks share one
    # answer, but a cell is small enough not to straddle zones often.
    grid_degrees = 0.01

    def compute(self, geom: GEOSGeometry, window: Window | None, params: dict) -> Computed:
        # NWS accepts at most four decimal places in `point`.
        request = {"point": f"{geom.y:.4f},{geom.x:.4f}"}
        payload = fetch_json(NWS_ALERTS_URL, request)
        value = parse_alerts(payload)
        provenance = {
            "source": "nws",
            "url": NWS_ALERTS_URL,
            "request": request,
            "updated": payload.get("updated"),
        }
        return Computed(value, provenance)


def parse_alerts(payload: dict) -> dict:
    """Reduce an NWS alerts response to the fields the panel shows, most severe first.
    Raises AnalysisError if the shape is not what was verified."""
    try:
        alerts = [
            {
                "id": props["id"],
                "event": props["event"],
                "headline": props.get("headline"),
                "severity": props.get("severity") or "Unknown",
                "urgency": props.get("urgency"),
                "certainty": props.get("certainty"),
                "effective": props.get("effective"),
                "onset": props.get("onset"),
                "expires": props.get("expires"),
                "ends": props.get("ends"),
                "sender_name": props.get("senderName"),
                "area": props.get("areaDesc"),
                "description": props.get("description"),
                "instruction": props.get("instruction"),
            }
            for props in (feature["properties"] for feature in payload["features"])
        ]
    except (KeyError, TypeError) as error:
        raise AnalysisError(f"unexpected NWS alerts response shape: {error!r}") from error

    def rank(alert):
        severity = alert["severity"]
        return SEVERITY_ORDER.index(severity) if severity in SEVERITY_ORDER else len(SEVERITY_ORDER)

    return {"title": payload.get("title"), "alerts": sorted(alerts, key=rank)}
