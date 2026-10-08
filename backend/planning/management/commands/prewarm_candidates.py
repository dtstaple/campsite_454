"""
Pre-warm the campsite search for demo trails (TM05-104).

    make prewarm TRAILS="Van Hoevenberg,Phelps Trail,Deer Pond Trail,Cheney Pond-Irishtown"
    .venv/bin/python backend/manage.py prewarm_candidates "Van Hoevenberg" "Deer Pond Trail"

The first "Find campsites along this trail" on a trail samples terrain from 3DEP and takes
15-35 s; after that the answer is in the analysis cache and comes back in milliseconds
(docs/candidates.md). This runs that search ahead of time, for the same corridor the panel
opens with (500 m), plus the trail's elevation profile so opening the panel is instant too.
It prints the time each one took. Running it again is quick: everything is cached.

A name is looked up as the trail panel would open it:
  1. a named route: exact name, else the longest whose name starts with it, else the longest
     whose name contains it ("Van Hoevenberg" -> "Van Hoevenberg Trail");
  2. otherwise named trail ways with exactly that name, opened as assembled trails
     (TM05-97). Ways of one name that don't connect are separate trails, and each is warmed.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError

from analysis.analyses.elevation import RouteProfile
from analysis.base import AnalysisError
from api.routes import DEFAULT_WITHIN_M, MAX_WITHIN_M, trail_for_way
from geodata.models import Trail, TrailRoute
from planning.candidate_views import candidates_payload


def routes_for(name: str) -> list[TrailRoute]:
    """The trails a demo name stands for: one route, or every assembled trail of that name."""
    name = name.strip()
    named = TrailRoute.objects.exclude(name="").order_by("-length_m", "osm_id")
    for lookup in ("name__iexact", "name__istartswith", "name__icontains"):
        route = named.filter(**{lookup: name}).first()
        if route is not None:
            return [route]
    trails, seen = [], set()
    for way in Trail.objects.filter(name__iexact=name).order_by("-length_m", "source_id"):
        _, route, _ = trail_for_way(way.source_id)
        if route.source_id not in seen:
            seen.add(route.source_id)
            trails.append(route)
    return trails


class Command(BaseCommand):
    help = "Run and cache the campsite search (and profile) for demo trails."

    def add_arguments(self, parser):
        parser.add_argument("trails", nargs="+", help="Trail names; commas also separate them.")
        parser.add_argument(
            "--within",
            type=int,
            default=DEFAULT_WITHIN_M,
            help=f"Corridor in metres, as the panel's 'within' (default {DEFAULT_WITHIN_M}).",
        )

    def handle(self, *args, **options):
        within = options["within"]
        if not 0 < within <= MAX_WITHIN_M:
            raise CommandError(f"--within must be 1-{MAX_WITHIN_M} m")
        names = [n.strip() for arg in options["trails"] for n in arg.split(",") if n.strip()]
        missing = []
        started = time.perf_counter()
        for name in names:
            routes = routes_for(name)
            if not routes:
                missing.append(name)
                self.stdout.write(self.style.ERROR(f"{name}: no named trail by that name"))
                continue
            for route in routes:
                miles = (route.length_m or 0) / 1609.344
                self.stdout.write(f"{name} -> {route.name} ({route.source_id}, {miles:.1f} mi)")
                self.stdout.write(f"  profile   {self._profile(route)}")
                self.stdout.write(f"  campsites {self._campsites(route, within)}")
        self.stdout.write(f"Done in {time.perf_counter() - started:.1f} s.")
        if missing:
            raise CommandError(f"Not found: {', '.join(missing)}")

    def _profile(self, route) -> str:
        started = time.perf_counter()
        try:
            outcome = RouteProfile().run(route.geom)
        except AnalysisError as error:
            return f"unavailable ({error})"
        state = "cached" if outcome.cached else "computed"
        return f"{time.perf_counter() - started:5.1f} s  {state}"

    def _campsites(self, route, within: int) -> str:
        started = time.perf_counter()
        payload = candidates_payload(route, within)
        took = time.perf_counter() - started
        if payload["status"] != "ok":
            return f"{took:5.1f} s  unavailable ({payload['reason']}); run it again later"
        state = "cached" if payload["cached"] else "computed"
        found = len(payload["candidates"])
        detail = f"{found} potential spot{'s' if found != 1 else ''}"
        if payload["reason"]:
            detail += f" ({payload['reason']})"
        return f"{took:5.1f} s  {state}, {detail}, within {within} m"
