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

Filters (TM05-85) narrow either list, and all of them combine:

    min_length_m, max_length_m       the route's length
    min_gain_m, max_gain_m           its climb (stored facts: needs a computed profile)
    difficulty=easy,moderate,hard    any of these
    route_type=loop,out_and_back,point_to_point
    campsites_within_m=500           a campsite within this distance of the route

They read the stored RouteFacts (enrichment/route_facts.py). A route whose facts cannot
answer an active filter -- usually no profile yet, so no gain or difficulty -- is left out
and counted in `unknown`, so the UI can say so rather than pretend it does not exist.
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
from enrichment.models import RouteFacts
from geodata.models import METRIC_SRID, TrailRoute

DIFFICULTIES = ("easy", "moderate", "hard")
ROUTE_TYPES = ("loop", "out_and_back", "point_to_point")

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


def float_param(request, name: str) -> float | None:
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except ValueError:
        raise InvalidParameter(f"{name} must be a number, got {raw!r}") from None
    if value < 0:
        raise InvalidParameter(f"{name} must be zero or more, got {raw!r}")
    return value


def choice_param(request, name: str, allowed: tuple[str, ...]) -> set[str]:
    raw = request.query_params.get(name)
    if not raw:
        return set()
    chosen = {part.strip() for part in raw.split(",") if part.strip()}
    unknown = chosen - set(allowed)
    if unknown:
        raise InvalidParameter(
            f"{name} values must be among {', '.join(allowed)}; got {', '.join(sorted(unknown))}"
        )
    return chosen


def parse_filters(request) -> dict:
    return {
        "min_length_m": float_param(request, "min_length_m"),
        "max_length_m": float_param(request, "max_length_m"),
        "min_gain_m": float_param(request, "min_gain_m"),
        "max_gain_m": float_param(request, "max_gain_m"),
        "difficulty": choice_param(request, "difficulty", DIFFICULTIES),
        "route_type": choice_param(request, "route_type", ROUTE_TYPES),
        "campsites_within_m": float_param(request, "campsites_within_m"),
    }


def passes(route: TrailRoute, filters: dict) -> bool | None:
    """True or False if the route's facts answer every active filter, None if they cannot
    (unknown) -- for example a gain filter on a route with no profile yet."""
    length = route.length_m or 0
    if filters["min_length_m"] is not None and length < filters["min_length_m"]:
        return False
    if filters["max_length_m"] is not None and length > filters["max_length_m"]:
        return False
    needs_facts = any(
        filters[key] not in (None, set())
        for key in ("min_gain_m", "max_gain_m", "difficulty", "route_type", "campsites_within_m")
    )
    if not needs_facts:
        return True
    try:
        facts = route.facts
    except RouteFacts.DoesNotExist:
        facts = None
    if facts is None:
        return None
    gain_filtered = filters["min_gain_m"] is not None or filters["max_gain_m"] is not None
    if gain_filtered or filters["difficulty"]:
        if facts.gain_m is None:
            return None
    if filters["min_gain_m"] is not None and facts.gain_m < filters["min_gain_m"]:
        return False
    if filters["max_gain_m"] is not None and facts.gain_m > filters["max_gain_m"]:
        return False
    if filters["difficulty"] and facts.difficulty not in filters["difficulty"]:
        return False
    if filters["route_type"] and facts.route_type not in filters["route_type"]:
        return False
    within = filters["campsites_within_m"]
    if within is not None and (
        facts.nearest_campsite_m is None or facts.nearest_campsite_m > within
    ):
        return False
    return True


def gain_of(route: TrailRoute) -> float | None:
    try:
        if route.facts.gain_m is not None:
            return route.facts.gain_m
    except RouteFacts.DoesNotExist:
        pass
    outcome = RouteProfile().lookup(route.geom, {})
    return outcome.value["stats"]["gain_m"] if outcome else None


@api_view(["GET"])
def route_search_view(request):
    try:
        limit = _int_param(request, "limit", DEFAULT_LIMIT, MAX_LIMIT)
        centre = parse_point(request.query_params.get("near"))
        raw_bbox = request.query_params.get("bbox")
        bbox = parse_bbox(raw_bbox) if raw_bbox else None
        filters = parse_filters(request)
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
    named = [r for r in routes.select_related("facts").defer("raw") if matches(r.name, words)]
    verdicts = [(route, passes(route, filters)) for route in named]
    candidates = [route for route, ok in verdicts if ok]
    unknown = sum(1 for _, ok in verdicts if ok is None)
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
            # Routes the active filters could not judge (no profile yet, say): left out.
            "unknown": unknown,
            "results": results,
        }
    )
