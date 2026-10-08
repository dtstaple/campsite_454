"""
Potential campsites along a trail (TM05-99). Contract: docs/api.md, "Potential campsites".

    GET /api/routes/<osm_id>/candidates/[?campsites_within_m=500]
    GET /api/trails/<source_id>/candidates/[?campsites_within_m=500]   a clicked way's trail

The search is planning/candidates.py; answers are cached per route geometry, corridor and
config (the analysis cache), so the second request for a trail is a lookup.
"""

import time

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from analysis.base import AnalysisError
from api.routes import DEFAULT_WITHIN_M, MAX_WITHIN_M, trail_for_way
from api.views import InvalidParameter, _bad_request, _int_param
from geodata.models import TrailRoute

from .candidates import TrailCandidates


def candidates_payload(route, within: int) -> dict:
    started = time.perf_counter()
    try:
        outcome = TrailCandidates().run(route.geom, {"within_m": within})
    except AnalysisError as error:
        return {
            "status": "unavailable",
            "reason": str(error),
            "within_m": within,
            "candidates": [],
            "counts": None,
        }
    value = outcome.value
    return {
        "status": "ok",
        "within_m": within,
        "candidates": value["candidates"],
        "counts": value["counts"],
        "reason": value["reason"],
        "cached": outcome.cached,
        "compute_ms": value["compute_ms"],
        "response_ms": round((time.perf_counter() - started) * 1000),
        "computed_at": outcome.computed_at,
    }


def _within(request) -> int:
    return _int_param(request, "campsites_within_m", DEFAULT_WITHIN_M, MAX_WITHIN_M)


@api_view(["GET"])
def route_candidates_view(request, osm_id: int):
    try:
        within = _within(request)
    except InvalidParameter as exc:
        return _bad_request(exc)
    route = get_object_or_404(TrailRoute, osm_id=osm_id)
    return Response(candidates_payload(route, within))


@api_view(["GET"])
def way_candidates_view(request, source_id: str):
    try:
        within = _within(request)
    except InvalidParameter as exc:
        return _bad_request(exc)
    _, route, _ = trail_for_way(source_id)
    return Response(candidates_payload(route, within))
