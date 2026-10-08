"""
Overnight plan endpoints (TM05-81). Contract: docs/api.md, "Overnight plans".

    POST   /api/plans/preview/       work out a plan without saving it
    GET    /api/plans/[?osm_id=|?from_way=]   the user's plans, optionally for one trail
    POST   /api/plans/               save a plan
    GET    /api/plans/<id>/          one plan, worked out against its trail
    PATCH  /api/plans/<id>/          rename it or change its stops
    DELETE /api/plans/<id>/          delete it
    GET    /api/plans/<id>/gpx/      the plan as GPX: track, stops, the user's waypoints

A plan body names its trail with `osm_id` (a route) or `from_way` (an assembled trail,
TM05-97) and its stops with `stop_ids`, campsite source ids in any order.

Token-authenticated, and every query starts from request.user, as for waypoints (views.py).
"""

from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.gpx import Waypoint as GpxWaypoint
from api.gpx import build_gpx, track_points
from api.routes import DEFAULT_WITHIN_M, gpx_response, trail_for_way
from geodata.models import Campsite, TrailRoute

from .models import PlanStop, TripPlan
from .plans import CANDIDATE_PREFIX, CandidateStop, PlanError, build_plan, is_candidate
from .queries import as_gpx, waypoints_near

MAX_PLANS_PER_USER = 200
NAME_MAX = TripPlan._meta.get_field("name").max_length


def _resolve_trail(osm_id, from_way):
    """The route a plan is along. PlanError for a body that names none, 404 for one that
    names a trail that does not exist."""
    if osm_id not in (None, ""):
        try:
            osm_id = int(osm_id)
        except (TypeError, ValueError):
            raise PlanError("osm_id must be a number.") from None
        return get_object_or_404(TrailRoute, osm_id=osm_id)
    if from_way:
        _, route, _ = trail_for_way(str(from_way))
        return route
    raise PlanError("Say which trail: osm_id for a route, or from_way for a trail way.")


def _sites(stop_ids):
    """Campsite rows for campsite ids, CandidateStops for potential campsites (TM05-99)."""
    if not isinstance(stop_ids, list) or not all(isinstance(i, str) for i in stop_ids):
        raise PlanError("stop_ids must be a list of campsite ids.")
    if len(stop_ids) != len(set(stop_ids)):
        raise PlanError("Each campsite can be a stop only once.")
    candidates = [CandidateStop(i) for i in stop_ids if i.startswith(CANDIDATE_PREFIX)]
    mapped = [i for i in stop_ids if not i.startswith(CANDIDATE_PREFIX)]
    sites = list(Campsite.objects.filter(source_id__in=mapped).select_related("facts"))
    missing = sorted(set(mapped) - {site.source_id for site in sites})
    if missing:
        raise PlanError(f"No campsite with id {', '.join(missing)}.")
    return sites + candidates


def _stop_rows(plan, sites):
    return [
        PlanStop(plan=plan, candidate_id=site.source_id, point=site.geom)
        if is_candidate(site)
        else PlanStop(plan=plan, campsite=site)
        for site in sites
    ]


def _public(plan: dict) -> dict:
    return {key: value for key, value in plan.items() if not key.startswith("_")}


def _saved(plan: TripPlan, worked: dict | None) -> dict:
    head = {
        "id": plan.id,
        "name": plan.name,
        "osm_id": plan.osm_id,
        "from_way": plan.from_way or None,
        "trail_name": plan.trail_name,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }
    return {**head, **_public(worked)} if worked else head


def _work_out(plan: TripPlan) -> dict:
    route = _resolve_trail(plan.osm_id, plan.from_way)
    sites = [
        stop.campsite if stop.campsite_id else CandidateStop(stop.candidate_id)
        for stop in plan.stops.select_related("campsite__facts")
    ]
    return build_plan(route, sites)


def _bad(error: PlanError):
    return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def plan_preview_view(request):
    try:
        route = _resolve_trail(request.data.get("osm_id"), request.data.get("from_way"))
        return Response(_public(build_plan(route, _sites(request.data.get("stop_ids")))))
    except PlanError as error:
        return _bad(error)


@api_view(["GET", "POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def plans_view(request):
    mine = TripPlan.objects.filter(user=request.user)
    if request.method == "GET":
        if request.query_params.get("osm_id"):
            try:
                mine = mine.filter(osm_id=int(request.query_params["osm_id"]))
            except ValueError:
                return _bad(PlanError("osm_id must be a number."))
        elif request.query_params.get("from_way"):
            mine = mine.filter(from_way=request.query_params["from_way"])
        return Response(
            [
                {**_saved(plan, None), "nights": plan.nights}
                for plan in mine.annotate(nights=Count("stops"))
            ]
        )

    if mine.count() >= MAX_PLANS_PER_USER:
        return _bad(PlanError(f"You can keep up to {MAX_PLANS_PER_USER} plans."))
    try:
        name = _clean_name(request.data.get("name"))
        route = _resolve_trail(request.data.get("osm_id"), request.data.get("from_way"))
        sites = _sites(request.data.get("stop_ids"))
        worked = build_plan(route, sites)
    except PlanError as error:
        return _bad(error)
    with transaction.atomic():
        plan = TripPlan.objects.create(
            user=request.user,
            name=name or f"{route.name}: {worked['nights']} nights",
            osm_id=route.osm_id,
            from_way="" if route.osm_id else str(request.data.get("from_way")),
            trail_name=route.name,
        )
        PlanStop.objects.bulk_create(_stop_rows(plan, sites))
    return Response(_saved(plan, worked), status=status.HTTP_201_CREATED)


def _clean_name(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PlanError("name must be text.")
    value = value.strip()
    if len(value) > NAME_MAX:
        raise PlanError(f"Keep the name under {NAME_MAX} characters.")
    return value


@api_view(["GET", "PATCH", "DELETE"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def plan_view(request, pk: int):
    plan = get_object_or_404(TripPlan, pk=pk, user=request.user)
    if request.method == "DELETE":
        plan.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    try:
        if request.method == "PATCH":
            name = _clean_name(request.data.get("name")) if "name" in request.data else None
            sites = _sites(request.data["stop_ids"]) if "stop_ids" in request.data else None
            if sites is not None:
                route = _resolve_trail(plan.osm_id, plan.from_way)
                build_plan(route, sites)  # validates before anything changes
            with transaction.atomic():
                if name:
                    plan.name = name
                if sites is not None:
                    plan.stops.all().delete()
                    PlanStop.objects.bulk_create(_stop_rows(plan, sites))
                plan.save()
        return Response(_saved(plan, _work_out(plan)))
    except PlanError as error:
        return _bad(error)


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def plan_gpx_view(request, pk: int):
    plan = get_object_or_404(TripPlan, pk=pk, user=request.user)
    try:
        worked = _work_out(plan)
    except PlanError as error:
        return _bad(error)
    line_m, profile = worked["_line_m"], worked["_profile"]
    track = track_points(
        line_m,
        profile["distance_m"] if profile else None,
        profile["elevation_m"] if profile else None,
    )
    stops = [
        GpxWaypoint(
            lon=stop["lon"],
            lat=stop["lat"],
            name=f"Night {stop['night']}: {stop['display_name'] or 'Campsite'}",
            desc=_stop_desc(stop, worked["days"]),
            sym="Campground" if stop["kind"] == "campsite" else "Flag, Red",
            type="overnight-stop" if stop["kind"] == "campsite" else "overnight-stop:unverified",
        )
        for stop in worked["stops"]
    ]
    mine = as_gpx(waypoints_near(request.user, line_m, DEFAULT_WITHIN_M))
    desc = (
        f"{worked['nights']} nights on {plan.trail_name}, "
        f"{worked['totals']['distance_m'] / 1000:.1f} km."
    )
    return gpx_response(plan.name, build_gpx(plan.name, track, stops + mine, desc=desc))


def _stop_desc(stop: dict, days: list[dict]) -> str:
    day = days[stop["night"] - 1]
    parts = [f"Day {day['day']}: {day['distance_m'] / 1000:.1f} km"]
    if day["gain_m"] is not None:
        parts.append(f"+{day['gain_m']:.0f} m / -{day['loss_m']:.0f} m")
    parts.append(stop["legality"]["label"])
    return ". ".join(parts)
