"""
Routes across connected trails (TM05-119). Contract: docs/api.md, "Planned routes".

    POST /api/routing/plan/                       {points: [[lon, lat], ...], cost}
    GET  /api/routing/<route_id>/                 the same route again, by its id
    GET  /api/routing/<route_id>/candidates/      Find campsites along it (TM05-99)
    GET  /api/routing/<route_id>/gpx/             the GPX download (TM05-79)

All four take ?campsites_within_m=, like a trail. The route detail is the trail panel's
payload (api/routes.py `route_detail`) plus a `planned` block: the stops, legs, trails
used and timings. Overnight plans take the route id as `planned_route` (planning).
"""

import time

from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.authentication import OptionalTokenAuthentication
from accounts.weights import config_for
from api.routes import DEFAULT_WITHIN_M, MAX_WITHIN_M, gpx_response, route_detail, route_gpx
from api.views import InvalidParameter, _bad_request, _int_param
from planning.candidate_views import candidates_payload

from .service import PlanningError, plan, resolve, summary


def _within(request) -> int:
    return _int_param(request, "campsites_within_m", DEFAULT_WITHIN_M, MAX_WITHIN_M)


def _cannot(error: PlanningError) -> Response:
    return Response({"error": str(error)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)


def _detail(request, planned, within: int, started: float) -> Response:
    detail = route_detail(planned.trail_route, within, config_for(request.user))
    block = summary(planned)
    block["timing_ms"]["total"] = round((time.perf_counter() - started) * 1000, 1)
    return Response({**detail, "assembled": False, "assembly": None, "planned": block})


@api_view(["POST"])
@authentication_classes([OptionalTokenAuthentication])
@permission_classes([AllowAny])
def plan_route_view(request):
    started = time.perf_counter()
    try:
        within = _within(request)
        planned = plan(request.data.get("points"), request.data.get("cost") or "naismith")
    except InvalidParameter as exc:
        return _bad_request(exc)
    except PlanningError as error:
        return _cannot(error)
    return _detail(request, planned, within, started)


@api_view(["GET"])
@authentication_classes([OptionalTokenAuthentication])
@permission_classes([AllowAny])
def planned_route_view(request, route_id: str):
    started = time.perf_counter()
    try:
        within = _within(request)
        planned = resolve(route_id)
    except InvalidParameter as exc:
        return _bad_request(exc)
    except PlanningError as error:
        return _cannot(error)
    return _detail(request, planned, within, started)


@api_view(["GET"])
def planned_candidates_view(request, route_id: str):
    try:
        within = _within(request)
        planned = resolve(route_id)
    except InvalidParameter as exc:
        return _bad_request(exc)
    except PlanningError as error:
        return _cannot(error)
    return Response(candidates_payload(planned.trail_route, within))


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([AllowAny])
def planned_gpx_view(request, route_id: str):
    try:
        within = _within(request)
        planned = resolve(route_id)
    except InvalidParameter as exc:
        return _bad_request(exc)
    except PlanningError as error:
        return _cannot(error)
    route = planned.trail_route
    return gpx_response(route.name, route_gpx(route, within, request.user))
