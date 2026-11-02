"""
GET /api/viewshed/?lat=&lon=[&radius_m=] -- what the terrain lets you see from any point
on the map (TM05-151), for the map's "What can I see from here?".

The campsite viewshed (TM05-142) is precomputed per site; this one is computed on request
through the analysis cache, per rounded location and radius (analysis/analyses/
viewshed.py). Contract: docs/api.md, "Viewshed from any point".
"""

from django.contrib.gis.geos import Point
from rest_framework.decorators import api_view
from rest_framework.response import Response

from analysis.analyses.viewshed import OutsideCoverage, PointViewshed, TerrainUnavailable
from analysis.base import AnalysisError
from api.conditions import _coordinate
from terrain.payload import NOTE

#: The short label the map shows on the overlay; NOTE is the longer caveat.
LABEL = "Bare-earth elevation"


def summary(area_km2: float, direction: str | None, radius_m: int) -> str:
    """The overlay's one line: "About 7.1 km² visible within 10 km, mostly to the east"."""
    within = f"within {radius_m / 1000:g} km"
    if area_km2 < 0.05:
        return f"Almost nothing visible {within}: the ground closes in all around."
    seen = f"About {area_km2:.1f} km² visible {within}"
    if direction == "all around":
        return f"{seen}, in every direction."
    if direction:
        return f"{seen}, mostly to the {direction}."
    return f"{seen}."


def _radius(request) -> float | None:
    raw = request.query_params.get("radius_m")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("radius_m must be a number of metres") from None
    if not value > 0:
        raise ValueError("radius_m must be greater than 0")
    return value


@api_view(["GET"])
def viewshed_view(request):
    try:
        lat = _coordinate(request, "lat", 90)
        lon = _coordinate(request, "lon", 180)
        radius = _radius(request)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)

    params = {} if radius is None else {"radius_m": radius}
    try:
        outcome = PointViewshed().run(Point(lon, lat, srid=4326), params)
    except OutsideCoverage as error:
        return Response({"error": str(error)}, status=422)
    except TerrainUnavailable as error:
        return Response({"error": str(error)}, status=503)
    except AnalysisError as error:
        return Response({"error": str(error)}, status=422)

    value = outcome.value
    return Response(
        {
            "type": "Feature",
            "geometry": value["geometry"],
            "properties": {
                "observer": value["observer"],
                "region": value["region"],
                "radius_m": value["radius_m"],
                "eye_height_m": value["eye_height_m"],
                "resolution_m": value["resolution_m"],
                "area_km2": value["area_km2"],
                "direction": value["direction"],
                "summary": summary(value["area_km2"], value["direction"], value["radius_m"]),
                "label": LABEL,
                "note": NOTE,
                "cached": outcome.cached,
                "computed_at": outcome.computed_at.isoformat(),
            },
        }
    )
