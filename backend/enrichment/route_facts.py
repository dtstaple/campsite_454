"""
Compute and store a route's facts (TM05-85): length, climb, difficulty, route type, and how
near its nearest campsite is. The rules are TM05-82's (geodata/route_rating.py); this file
only gathers them into one stored row per route.
"""

from __future__ import annotations

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db.models import Min
from django.utils import timezone

from analysis.analyses.elevation import RouteProfile, stitch
from enrichment.models import RouteFacts
from geodata.models import Campsite, TrailRoute
from geodata.route_rating import difficulty, route_type

#: "Has campsites within X" offers up to 2 km (the trail panel's largest "within").
NEAREST_CAMPSITE_MAX_M = 2000


def nearest_campsite_m(route: TrailRoute) -> float | None:
    nearby = Campsite.objects.filter(
        geom_m__dwithin=(route.geom_m, D(m=NEAREST_CAMPSITE_MAX_M))
    ).annotate(distance=Distance("geom_m", route.geom_m))
    found = nearby.aggregate(nearest=Min("distance"))["nearest"]
    return found.m if found is not None else None


def save_route_facts(route: TrailRoute, profile: dict | None = None, line_m=None) -> RouteFacts:
    """Upsert the route's facts. `profile` is its profile value if the caller has one;
    otherwise the cached profile is used if there is one, and never fetched."""
    if profile is None:
        outcome = RouteProfile().lookup(route.geom, {})
        profile = outcome.value if outcome else None
    if line_m is None:
        line_m, _ = stitch(route.geom)
    stats = (profile or {}).get("stats") or {}
    rated = (
        difficulty(stats["length_m"], stats["gain_m"], stats["loss_m"])
        if "gain_m" in stats
        else None
    )
    kind = route_type(route, line_m, profile["elevation_m"] if profile else None)
    facts, _ = RouteFacts.objects.update_or_create(
        route=route,
        defaults={
            "computed_at": timezone.now(),
            "length_m": route.length_m or line_m.length,
            "gain_m": stats.get("gain_m"),
            "loss_m": stats.get("loss_m"),
            "difficulty": rated["rating"] if rated else "",
            "shenandoah": rated["shenandoah"] if rated else None,
            "route_type": kind["type"],
            "route_type_estimated": kind["estimated"],
            "nearest_campsite_m": nearest_campsite_m(route),
        },
    )
    return facts
