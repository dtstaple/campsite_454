"""
Trail search and the Discover list (TM05-74).

    GET /api/routes/search/?q=marcy&near=-73.96,44.11&bbox=w,s,e,n&limit=25

One endpoint does both jobs:

- **Search** (`q`): named routes whose name contains every word of the query, ignoring
  case and accents ("lac" finds "Lac Clear Trail", "loj" finds "Adirondak Loj").
- **Discover list** (`bbox`): named routes in or near the current view. "Near" is the view
  grown by NEAR_MARGIN of its size on every side, so a trail just off-screen is listed.

Either way, results are sorted by their distance from the view centre (`near`), measured
in metres to the nearest point of each route, and ties go to the name. Gain comes from the
route's cached elevation profile, if there is one; it is never computed here, so a list
that refreshes on every pan never waits on 3DEP.

Matching is done in Python on normalised names rather than with Postgres' `unaccent`:
the route table holds hundreds of rows, and that avoids a database extension.
"""

from __future__ import annotations

import unicodedata

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from rest_framework.decorators import api_view
from rest_framework.response import Response

from analysis.analyses.elevation import RouteProfile
from api.bbox import InvalidBbox, parse_bbox
from api.layers import envelope
from api.views import InvalidParameter, _bad_request, _int_param
from geodata.models import METRIC_SRID, TrailRoute

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
#: "Near the view": the bbox grown by this share of its width and height on each side.
NEAR_MARGIN = 0.5


def normalise(text: str) -> str:
    """Lower case, accents stripped: "Lac Clair" and "lac clair" and "Lac Clâir" match."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def matches(name: str, words: list[str]) -> bool:
    folded = normalise(name)
    return all(word in folded for word in words)


def grown(bbox, margin=NEAR_MARGIN):
    west, south, east, north = bbox
    dx, dy = (east - west) * margin, (north - south) * margin
    return (max(-180, west - dx), max(-90, south - dy), min(180, east + dx), min(90, north + dy))


def parse_point(raw: str | None) -> Point | None:
    if not raw:
        return None
    try:
        lon, lat = (float(part) for part in raw.split(","))
    except ValueError:
        raise InvalidParameter(f"near must be lon,lat in decimal degrees, got {raw!r}") from None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise InvalidParameter(f"near is not a valid longitude/latitude: {raw!r}")
    return Point(lon, lat, srid=4326)


def gain_of(route: TrailRoute) -> float | None:
    outcome = RouteProfile().lookup(route.geom, {})
    return outcome.value["stats"]["gain_m"] if outcome else None


@api_view(["GET"])
def route_search_view(request):
    try:
        limit = _int_param(request, "limit", DEFAULT_LIMIT, MAX_LIMIT)
        centre = parse_point(request.query_params.get("near"))
        raw_bbox = request.query_params.get("bbox")
        bbox = parse_bbox(raw_bbox) if raw_bbox else None
    except (InvalidBbox, InvalidParameter) as exc:
        return _bad_request(exc)

    query = (request.query_params.get("q") or "").strip()
    words = [normalise(word) for word in query.split()]
    if not words and bbox is None:
        return _bad_request(InvalidParameter("Give a search term (q) or a view (bbox)."))

    routes = TrailRoute.objects.exclude(name="")
    if bbox is not None and not words:
        # The Discover list: in or near the view. A name search looks everywhere.
        routes = routes.filter(geom__bboverlaps=envelope(grown(bbox)))
    if centre is not None:
        metric_centre = centre.transform(METRIC_SRID, clone=True)
        routes = routes.annotate(distance=Distance("geom_m", metric_centre))
    candidates = [route for route in routes.defer("raw") if matches(route.name, words)]
    if centre is not None:
        candidates.sort(key=lambda route: (route.distance.m, normalise(route.name)))
    else:
        candidates.sort(key=lambda route: (normalise(route.name), route.osm_id))

    results = []
    for route in candidates[:limit]:
        centroid = route.geom.centroid
        gain = gain_of(route)
        results.append(
            {
                "osm_id": route.osm_id,
                "name": route.name,
                "length_m": round(route.length_m or 0, 1),
                "gain_m": round(gain, 1) if gain is not None else None,
                "centroid": [round(centroid.x, 6), round(centroid.y, 6)],
                "distance_m": round(route.distance.m, 1) if centre is not None else None,
            }
        )
    return Response(
        {
            "query": query,
            "count": len(results),
            "truncated": len(candidates) > limit,
            "results": results,
        }
    )
