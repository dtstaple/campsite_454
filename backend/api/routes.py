"""
Named-route endpoints (TM05-60): what the trail panel reads.

    GET /api/routes/?bbox=w,s,e,n[&limit=][&simplify=]   routes in view, as GeoJSON
    GET /api/routes/<osm_id>/[?campsites_within_m=500]    one route in detail

The detail joins the three things built before it: the route (TM05-58), its elevation
profile (TM05-59, from the analysis cache), and the campsites along it with their scores
(TM05-43), found with metre-correct, indexed distance queries (TM05-42). Contract and
examples: docs/api.md.
"""

import json

from django.contrib.gis.db.models.functions import AsGeoJSON
from django.db import connection
from django.db.models import Value
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from analysis.analyses.elevation import RouteProfile, stitch
from analysis.base import AnalysisError
from api.bbox import InvalidBbox, parse_bbox
from api.gpx import CONTENT_TYPE, Waypoint, build_gpx, campsite_waypoints, track_points
from api.gpx import filename as gpx_filename
from api.layers import COORDINATE_PRECISION, SimplifyPreserveTopology, envelope
from api.views import InvalidParameter, _bad_request, _int_param, _simplify_param
from enrichment.models import CampsiteFacts
from enrichment.route_facts import save_route_facts
from geodata.assembly import assembled_route, route_for_way
from geodata.junctions import connections
from geodata.models import Campsite, Trail, TrailRoute
from geodata.route_rating import config as route_config
from geodata.route_rating import difficulty, position_along, route_type
from planning.queries import as_gpx, waypoints_near
from scoring.config import load as load_scoring_config
from scoring.engine import score_campsite
from scoring.verdict import legality_verdict

DEFAULT_ROUTE_LIMIT = 200
MAX_ROUTE_LIMIT = 1000
DEFAULT_WITHIN_M = 500
MAX_WITHIN_M = 5000
MAX_CAMPSITES = 100


@api_view(["GET"])
def routes_view(request):
    """Named routes whose geometry intersects the bbox, longest first."""
    try:
        bbox = parse_bbox(request.query_params.get("bbox"))
        limit = _int_param(request, "limit", DEFAULT_ROUTE_LIMIT, MAX_ROUTE_LIMIT)
        simplify = _simplify_param(request)
    except (InvalidBbox, InvalidParameter) as exc:
        return _bad_request(exc)

    geometry = SimplifyPreserveTopology("geom", Value(simplify)) if simplify else "geom"
    rows = list(
        TrailRoute.objects.filter(geom__bboverlaps=envelope(bbox))
        .exclude(name="")
        .order_by("-length_m", "osm_id")
        .annotate(geojson=AsGeoJSON(geometry, precision=COORDINATE_PRECISION))
        .values("osm_id", "name", "ref", "network", "operator", "length_m", "geojson")[: limit + 1]
    )
    truncated = len(rows) > limit
    rows = rows[:limit]
    return Response(
        {
            "type": "FeatureCollection",
            "bbox": list(bbox),
            "features": [
                {
                    "type": "Feature",
                    "id": row["osm_id"],
                    "geometry": json.loads(row["geojson"]),
                    "properties": {
                        "osm_id": row["osm_id"],
                        "name": row["name"],
                        "ref": row["ref"] or None,
                        "network": row["network"] or None,
                        "operator": row["operator"] or None,
                        "length_m": round(row["length_m"] or 0, 1),
                    },
                }
                for row in rows
            ],
            "metadata": {
                "returned": len(rows),
                "truncated": truncated,
                "limit": limit,
                "simplify": simplify,
            },
        }
    )


# Campsites within `within` metres of any route member, located along the stitched line.
# ST_DWithin on geom_m uses the campsite_geom_m_gist index; the route geometry is a
# constant, so it is not re-projected per row.
CAMPSITES_ALONG_SQL = """
WITH route AS (SELECT %s::geometry AS members, %s::geometry AS line)
SELECT c.id,
       ST_Distance(c.geom_m, route.members) AS from_route_m,
       ST_LineLocatePoint(route.line, c.geom_m) * ST_Length(route.line) AS along_m,
       ST_Distance(c.geom_m, route.line) AS from_line_m
FROM geodata_campsite c, route
WHERE ST_DWithin(c.geom_m, route.members, %s)
ORDER BY along_m, from_route_m
LIMIT %s
"""


def _profile_payload(route):
    try:
        outcome = RouteProfile().run(route.geom)
    except AnalysisError as error:
        return {"status": "unavailable", "reason": str(error)}
    value, provenance = outcome.value, outcome.provenance
    return {
        "status": "ok",
        "reason": None,
        "stats": value["stats"],
        "distance_m": value["distance_m"],
        "elevation_m": value["elevation_m"],
        "params": value["params"],
        "source": {
            "name": provenance.get("source"),
            "datasets": provenance.get("datasets"),
            "resolution_m": provenance.get("resolution_m"),
            "vertical_datum": provenance.get("vertical_datum"),
            "computed_at": provenance.get("computed_at"),
            "cached": outcome.cached,
        },
    }


def facts_of(site: Campsite) -> CampsiteFacts | None:
    try:
        return site.facts
    except CampsiteFacts.DoesNotExist:
        return None


def display_name(site: Campsite) -> dict:
    """`display_name` and `display_name_derived`, exactly as the campsite detail endpoint
    gives them, so the trail list and the panel always agree on a site's name."""
    source_name = (site.name or "").strip()
    try:
        facts = site.facts
    except CampsiteFacts.DoesNotExist:
        facts = None
    return {
        "display_name": (facts.display_name if facts else source_name) or None,
        "display_name_derived": bool(facts and facts.display_name_derived),
    }


@api_view(["GET"])
def route_detail_view(request, osm_id: int):
    """One route: properties, stitched line, elevation profile, campsites along it."""
    try:
        within = _int_param(request, "campsites_within_m", DEFAULT_WITHIN_M, MAX_WITHIN_M)
    except InvalidParameter as exc:
        return _bad_request(exc)

    route = get_object_or_404(TrailRoute, osm_id=osm_id)
    detail = route_detail(route, within)
    remember_facts(route, detail)
    return Response(detail)


@api_view(["GET"])
def way_trail_view(request, source_id: str):
    """The trail panel's detail for a clicked trail way (TM05-97): its named route when it
    is a member of one, otherwise a trail assembled from the connected ways that share its
    name. An unnamed way has no trail to open: 404, and the map keeps its small popup."""
    try:
        within = _int_param(request, "campsites_within_m", DEFAULT_WITHIN_M, MAX_WITHIN_M)
    except InvalidParameter as exc:
        return _bad_request(exc)

    way, route, assembled = trail_for_way(source_id)
    if not assembled:
        detail = route_detail(route, within)
        remember_facts(route, detail)
        return Response({**detail, "assembled": False, "assembly": None})
    detail = route_detail(route, within)
    detail["assembled"] = True
    detail["assembly"] = {
        "from_way": way.source_id,
        "ways": len(route.member_way_ids),
        "note": "Assembled from mapped segments",
    }
    return Response(detail)


def trail_for_way(source_id: str) -> tuple[Trail, TrailRoute, bool]:
    """A clicked way's trail: (way, route, assembled). Its named route when it is a member
    of one, otherwise the trail assembled from connected same-name ways (TM05-97). 404s
    for an unknown or unnamed way."""
    way = Trail.objects.filter(source_id=source_id).first()
    if way is None:
        raise Http404(f"No trail way with source_id {source_id!r}")
    if not (way.name or "").strip():
        raise Http404(f"{source_id} has no name, so there is no trail to assemble")
    route = route_for_way(way)
    if route is not None:
        return way, route, False
    return way, assembled_route(way), True


def remember_facts(route: TrailRoute, detail: dict) -> None:
    """Refresh the route's stored filter facts (TM05-85) from the profile just served, so a
    trail someone has opened is filterable by gain and difficulty from then on."""
    profile = detail["profile"]
    if profile["status"] != "ok":
        return
    value = {"stats": profile["stats"], "elevation_m": profile["elevation_m"]}
    save_route_facts(route, value)


def route_detail(route: TrailRoute, within: int) -> dict:
    """The route detail payload, for a stored route or an assembled one (TM05-97)."""
    line_m, path = stitch(route.geom)
    line = line_m.transform(4326, clone=True)

    with connection.cursor() as cursor:
        cursor.execute(
            CAMPSITES_ALONG_SQL, [route.geom_m.ewkt, line_m.ewkt, within, MAX_CAMPSITES + 1]
        )
        located = cursor.fetchall()
    truncated = len(located) > MAX_CAMPSITES
    located = located[:MAX_CAMPSITES]
    sites = Campsite.objects.select_related("facts").in_bulk([row[0] for row in located])

    config = load_scoring_config()
    along_settings = route_config()["along"]
    campsites = []
    for site_id, from_route, along, from_line in located:
        site = sites[site_id]
        result = score_campsite(site, config)
        campsites.append(
            {
                "id": site.source_id,
                "source": site.source,
                "name": site.name or None,
                # The same name the detail panel shows, derived when the source has none
                # (TM05-71, from TM05-64's enrichment).
                **display_name(site),
                "site_type": site.site_type,
                "lon": round(site.geom.x, 6),
                "lat": round(site.geom.y, 6),
                "distance_along_m": round(along, 1),
                "distance_from_route_m": round(from_route, 1),
                **position_along(along, line_m.length, from_line, along_settings),
                "score": result["score"],
                "score_breakdown": result,
                "legality": legality_verdict(site, facts_of(site), result["legal_status"]),
            }
        )

    profile = _profile_payload(route)
    profiled = profile["status"] == "ok"
    return {
        "osm_id": route.osm_id,
        "source_id": route.source_id,
        "name": route.name,
        "ref": route.ref or None,
        "network": route.network or None,
        "operator": route.operator or None,
        "length_m": round(route.length_m or 0, 1),
        "geometry": json.loads(route.geom.geojson),
        "line": {
            "type": "LineString",
            "coordinates": [[round(x, 6), round(y, 6)] for x, y in line.coords],
            "length_m": round(line_m.length, 1),
        },
        "path": path,
        "profile": profile,
        # TM05-82: difficulty needs the profile's gain; route type works without it.
        "difficulty": (
            difficulty(
                profile["stats"]["length_m"],
                profile["stats"]["gain_m"],
                profile["stats"]["loss_m"],
            )
            if profiled
            else None
        ),
        "route_type": route_type(route, line_m, profile["elevation_m"] if profiled else None),
        # TM05-101: the named trails this one meets at a junction node, by mile.
        "connections": connections(route, line_m),
        "campsites": {
            "within_m": within,
            "count": len(campsites),
            "truncated": truncated,
            "items": campsites,
        },
    }


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([AllowAny])
def route_gpx_view(request, osm_id: int):
    """A named route as a GPX 1.1 download (TM05-79): track plus campsite waypoints."""
    try:
        within = _int_param(request, "campsites_within_m", DEFAULT_WITHIN_M, MAX_WITHIN_M)
    except InvalidParameter as exc:
        return _bad_request(exc)
    route = get_object_or_404(TrailRoute, osm_id=osm_id)
    return gpx_response(route.name, route_gpx(route, within, request.user))


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([AllowAny])
def way_gpx_view(request, source_id: str):
    """A clicked way's trail (TM05-97) as a GPX 1.1 download."""
    try:
        within = _int_param(request, "campsites_within_m", DEFAULT_WITHIN_M, MAX_WITHIN_M)
    except InvalidParameter as exc:
        return _bad_request(exc)
    _, route, _ = trail_for_way(source_id)
    return gpx_response(route.name, route_gpx(route, within, request.user))


def route_gpx(
    route, within: int, user=None, extra_waypoints: list[Waypoint] | None = None
) -> bytes:
    """The GPX for a stored or assembled route, built from the trail panel's payload so the
    download matches what the user was looking at (api/gpx.py). A signed-in user's own
    waypoints within the same distance of the route are added (TM05-80)."""
    detail = route_detail(route, within)
    line_m, _ = stitch(route.geom)
    profile = detail["profile"]
    profiled = profile["status"] == "ok"
    track = track_points(
        line_m,
        profile["distance_m"] if profiled else None,
        profile["elevation_m"] if profiled else None,
    )
    waypoints = (
        campsite_waypoints(detail["campsites"]["items"])
        + as_gpx(waypoints_near(user, line_m, within))
        + list(extra_waypoints or [])
    )
    desc = f"{line_m.length / 1000:.1f} km. Campsites within {within} m of the trail."
    if not profiled:
        desc += " Elevation unavailable."
    return build_gpx(detail["name"] or "Trail", track, waypoints, desc=desc)


def gpx_response(name: str, body: bytes) -> HttpResponse:
    response = HttpResponse(body, content_type=CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{gpx_filename(name)}"'
    return response
