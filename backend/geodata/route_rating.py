"""
Difficulty and route type for a named route (TM05-82). Rules and thresholds: routes.yml;
explanation: docs/routes.md.

Difficulty is a formula, so it is exact for the data: Shenandoah's rating,
sqrt(gain_ft * 2 * distance_mi), banded into Easy / Moderate / Hard. "Gain" is the climb in
the route's harder direction, max(gain, loss), since a route can be walked either way.

Route type is partly a guess, and says so. A loop is measured: the ends meet. Otherwise
each end is classified from what is near it --

    summit     the end is (within summit_within_m) the route's highest point, on a route
               that climbs at least summit_min_relief_m
    connects   another trail, not one of the route's own ways, within connect_m
    pond       a lake or pond within pond_m
    dead_end   none of those

checked in that order: a summit is a destination even where other trails meet it, but a
junction at a lake is still a junction.

-- and the ends decide the type, with `estimated: true`:

    either end at a summit or pond          out_and_back (you walk to it and back)
    one end connects, the other dead-ends   out_and_back (a spur to nowhere we can see)
    otherwise (both connect, or both
    dead-end)                               point_to_point

Roads are not in the database, so a trailhead on a road reads as a dead end. That is why
two dead ends make point_to_point (both likely reach roads), and why every non-loop answer
is labelled estimated.
"""

from __future__ import annotations

import math
from functools import cache
from pathlib import Path

import yaml
from django.contrib.gis.geos import LineString, Point
from django.contrib.gis.measure import D

from geodata.models import METRIC_SRID, Trail, TrailRoute, WaterFeature

CONFIG_PATH = Path(__file__).resolve().parent / "routes.yml"
FT_PER_M = 3.28084
M_PER_MI = 1609.344

LOOP, OUT_AND_BACK, POINT_TO_POINT = "loop", "out_and_back", "point_to_point"
TYPE_LABELS = {LOOP: "Loop", OUT_AND_BACK: "Out & back", POINT_TO_POINT: "Point to point"}
SUMMIT, POND, CONNECTS, DEAD_END = "summit", "pond", "connects", "dead_end"


@cache
def config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


# --- difficulty --------------------------------------------------------------------------


def shenandoah_rating(length_m: float, gain_m: float) -> float:
    """sqrt(elevation gain in feet x 2 x distance in miles)."""
    return math.sqrt(max(gain_m, 0.0) * FT_PER_M * 2 * max(length_m, 0.0) / M_PER_MI)


def difficulty(
    length_m: float, gain_m: float, loss_m: float = 0.0, settings: dict | None = None
) -> dict:
    """Banded Shenandoah rating. The climb is the larger of gain and loss: a route mapped
    downhill (gain 0) is just as hard walked the other way, and the user may walk it either
    way, so it is rated in its harder direction."""
    settings = settings or config()["difficulty"]
    climb_m = max(gain_m, loss_m)
    rating = shenandoah_rating(length_m, climb_m)
    label = next(
        band["label"]
        for band in settings["bands"]
        if band["below"] is None or rating < band["below"]
    )
    return {
        "rating": label.lower(),
        "label": label,
        "shenandoah": round(rating, 1),
        "formula": "sqrt(climb_ft x 2 x distance_mi), one way, in the harder direction",
        "length_m": round(length_m, 1),
        "climb_m": round(climb_m, 1),
    }


# --- route type --------------------------------------------------------------------------


def classify_end(
    end: Point,
    elevation: float | None,
    elevations: list[float] | None,
    own_way_ids: set[str],
    settings: dict,
) -> str:
    """What one end of the route (a METRIC_SRID point) is at."""
    if elevation is not None and elevations:
        high, low = max(elevations), min(elevations)
        if (
            high - low >= settings["summit_min_relief_m"]
            and elevation >= high - settings["summit_within_m"]
        ):
            return SUMMIT
    if (
        Trail.objects.filter(geom_m__dwithin=(end, D(m=settings["connect_m"])))
        .exclude(source_id__in=own_way_ids)
        .exists()
    ):
        return CONNECTS
    if WaterFeature.objects.filter(
        feature_type="lake", geom_m__dwithin=(end, D(m=settings["pond_m"]))
    ).exists():
        return POND
    return DEAD_END


def decide(start: str, end: str) -> str:
    ends = {start, end}
    if ends & {SUMMIT, POND}:
        return OUT_AND_BACK
    if ends == {CONNECTS, DEAD_END}:
        return OUT_AND_BACK
    return POINT_TO_POINT


def route_type(
    route: TrailRoute,
    line_m: LineString,
    elevations: list[float] | None = None,
    settings: dict | None = None,
) -> dict:
    """The route's type from its stitched METRIC_SRID line (and its profile, if any)."""
    settings = settings or config()["route_type"]
    start = Point(line_m.coords[0], srid=METRIC_SRID)
    end = Point(line_m.coords[-1], srid=METRIC_SRID)
    gap = start.distance(end)
    if gap <= settings["loop_max_gap_m"]:
        return _type(LOOP, False, {"ends_apart_m": round(gap, 1)})

    own = {f"way/{way_id}" for way_id in (route.member_way_ids or [])}
    first = elevations[0] if elevations else None
    last = elevations[-1] if elevations else None
    at_start = classify_end(start, first, elevations, own, settings)
    at_end = classify_end(end, last, elevations, own, settings)
    return _type(
        decide(at_start, at_end),
        True,
        {"ends_apart_m": round(gap, 1), "start": at_start, "end": at_end},
    )


def _type(kind: str, estimated: bool, basis: dict) -> dict:
    return {"type": kind, "label": TYPE_LABELS[kind], "estimated": estimated, "basis": basis}
