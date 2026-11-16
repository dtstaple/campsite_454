"""
Auto-planned overnight stops along a trail or planned route (TM05-169).
docs/routing.md, "Auto-planning overnight stops", explains the method; the weights are in
autoplan.yml.

Given a route and a number of nights (or a daily distance target, which picks the number
of nights), it proposes one stop per night:

1. **Even split.** With D days (nights + 1), night k's ideal place is k x length / D.
2. **Windows.** Night k's stop is looked for within `window_fraction` of an even day
   either side of that place. Only stops whose legality verdict is "permitted" are
   eligible. A night whose window holds no permitted stop is reported as a gap ("No legal
   stop between mi 8.0 and mi 14.0") and left out, never filled with an unverified spot.
3. **Exact choice.** Among the eligible stops, dynamic programming over the nights finds
   the plan with the lowest total cost: each day's squared deviation from its share of
   the route's distance and of its climb, plus each stop's shortfall from a perfect
   score, weighted by the config. Windows don't overlap, so the nights stay in order, and
   the search is exact: it compares every combination without listing them.
4. **Explained.** Each chosen stop says why: its verdict and score, how many legal stops
   its window held, and what the higher-scoring alternative would have done to the days.

`solve()` is pure (numbers in, choices out), so the method is tested without a database.
`auto_plan()` gathers the stops from the database and returns the worked-out plan too.
Ties break the same way every time: options are taken in order along the route, then by
id, and only a strictly lower cost replaces the best so far. The same input always gives
the same plan.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml
from django.db import connection

from analysis.analyses.elevation import stitch
from api.routes import CAMPSITES_ALONG_SQL
from geodata.models import Campsite
from geodata.route_rating import ALONG, position_along
from geodata.route_rating import config as route_config
from scoring.config import load as load_scoring_config
from scoring.verdict import PERMITTED

from . import plans
from .candidates import TrailCandidates
from .days import day_stats, smoothed_profile, value_at

CONFIG_PATH = Path(__file__).with_name("autoplan.yml")
M_PER_MI = 1609.344
FT_PER_M = 3.28084
#: Floating-point slack when comparing costs, so ties break by order, not by rounding.
EPSILON = 1e-12


class AutoPlanError(ValueError):
    """A request the planner cannot answer, with a message for the person asking."""


@dataclass(frozen=True)
class Settings:
    window_fraction: float
    min_day_m: float
    w_distance: float
    w_gain: float
    w_score: float
    gain_floor_m: float
    unscored_score: float
    max_sites: int

    def weights(self) -> dict:
        return {"distance": self.w_distance, "gain": self.w_gain, "score": self.w_score}


def parse_settings(raw: dict) -> Settings:
    """Settings from autoplan.yml's mapping, checked so a bad edit fails loudly."""
    weights = raw.get("weights") or {}
    settings = Settings(
        window_fraction=float(raw["window_fraction"]),
        min_day_m=float(raw["min_day_m"]),
        w_distance=float(weights["distance"]),
        w_gain=float(weights["gain"]),
        w_score=float(weights["score"]),
        gain_floor_m=float(raw["gain_floor_m"]),
        unscored_score=float(raw["unscored_score"]),
        max_sites=int(raw["max_sites"]),
    )
    if not 0 < settings.window_fraction <= 0.5:
        raise ValueError("window_fraction must be above 0 and at most 0.5")
    if min(settings.w_distance, settings.w_gain, settings.w_score) < 0:
        raise ValueError("weights must be >= 0")
    if settings.min_day_m <= 0 or settings.gain_floor_m <= 0 or settings.max_sites < 1:
        raise ValueError("min_day_m, gain_floor_m and max_sites must be positive")
    if not 0 <= settings.unscored_score <= 100:
        raise ValueError("unscored_score must be 0-100")
    return settings


@cache
def load_settings() -> Settings:
    return parse_settings(yaml.safe_load(CONFIG_PATH.read_text()))


# --- formatting --------------------------------------------------------------------------


def mile_mark(metres: float) -> str:
    """'mi 8.0': a place along the route."""
    return f"mi {metres / M_PER_MI:.1f}"


def miles(metres: float) -> str:
    return f"{metres / M_PER_MI:.1f} mi"


def feet(metres: float) -> str:
    return f"{round(metres * FT_PER_M):,} ft"


# --- the method (pure) -------------------------------------------------------------------


@dataclass(frozen=True)
class Option:
    """A place the planner could stop: a mapped campsite or a potential spot."""

    id: str
    along_m: float
    permitted: bool
    score: float | None
    name: str
    verdict_label: str


@dataclass
class Climb:
    """Cumulative climb along the route, for each day's gain while choosing. It sums every
    rise of the smoothed profile, without the plan's 3 m threshold, so it is additive; the
    plan shown afterwards measures each day exactly as the trail panel does."""

    distances: list[float]
    cumulative: list[float] = field(default_factory=list)
    #: How the plan itself measures the gain from one place to another (with its
    #: threshold), so the reasons quote the same figures as the day table.
    measure: Callable[[float, float], float] | None = None

    @classmethod
    def from_profile(cls, distances: list[float], smoothed: list[float]) -> Climb:
        total, cumulative = 0.0, [0.0]
        for previous, current in zip(smoothed, smoothed[1:], strict=False):
            total += max(0.0, current - previous)
            cumulative.append(total)
        return cls(list(distances), cumulative)

    def at(self, metres: float) -> float:
        return value_at(self.distances, self.cumulative, metres)

    @property
    def total(self) -> float:
        return self.cumulative[-1]

    def shown(self, start_m: float, end_m: float) -> float:
        """The gain from start_m to end_m as the day table shows it."""
        if self.measure is not None:
            return self.measure(start_m, end_m)
        return self.at(end_m) - self.at(start_m)


def days_for_target(length_m: float, target_m: float) -> int:
    """The number of days whose even split is closest to the daily target; on a tie, the
    shorter days. At least one."""
    low = max(1, math.floor(length_m / target_m))
    best = None
    for days in (low, low + 1):
        miss = abs(length_m / days - target_m)
        if best is None or miss < best[0] - EPSILON or abs(miss - best[0]) <= EPSILON:
            best = (miss, days)
    return best[1]


def _score(option: Option, settings: Settings) -> float:
    return settings.unscored_score if option.score is None else option.score


def solve(
    length_m: float,
    options: list[Option],
    nights: int,
    settings: Settings,
    climb: Climb | None = None,
) -> dict:
    """The best plan of `nights` stops along a route `length_m` long. Returns the chosen
    stops (with reasons), the nights left out for want of a legal stop, and the targets."""
    days = nights + 1
    day_m = length_m / days
    day_gain = climb.total / days if climb else None
    half = settings.window_fraction * day_m
    ordered = sorted(options, key=lambda o: (o.along_m, o.id))

    windows = []
    for night in range(1, nights + 1):
        start = max(0.0, night * day_m - half)
        end = min(length_m, night * day_m + half)
        inside = [o for o in ordered if start <= o.along_m <= end]
        windows.append(
            {
                "night": night,
                "start_m": start,
                "end_m": end,
                "legal": [o for o in inside if o.permitted],
                "other": [o for o in inside if not o.permitted],
            }
        )

    def day_cost(start_m: float, end_m: float, span: int) -> float:
        """A day (or `span` days run together, across a gap) from start_m to end_m."""
        want = span * day_m
        cost = settings.w_distance * ((end_m - start_m - want) / want) ** 2
        if climb is not None:
            want_gain = span * day_gain
            scale = max(want_gain, span * settings.gain_floor_m)
            gain = climb.at(end_m) - climb.at(start_m)
            cost += settings.w_gain * ((gain - want_gain) / scale) ** 2
        return cost

    def stop_cost(option: Option) -> float:
        return settings.w_score * (100 - _score(option, settings)) / 100

    # Dynamic programming: one layer per night that has a legal stop. Each state is
    # (position, night, cost so far, index of the state it came from, option).
    layers: list[list[tuple]] = [[(0.0, 0, 0.0, None, None)]]
    for window in windows:
        if not window["legal"]:
            continue
        layer = []
        for option in window["legal"]:
            best = None
            for index, (position, night, cost, _, _) in enumerate(layers[-1]):
                total = cost + day_cost(position, option.along_m, window["night"] - night)
                if best is None or total < best[0] - EPSILON:
                    best = (total, index)
            layer.append(
                (option.along_m, window["night"], best[0] + stop_cost(option), best[1], option)
            )
        layers.append(layer)

    best = None
    for index, (position, night, cost, _, _) in enumerate(layers[-1]):
        total = cost + day_cost(position, length_m, days - night)
        if best is None or total < best[0] - EPSILON:
            best = (total, index)
    total_cost, index = best

    chosen: list[Option] = []
    for layer in reversed(layers[1:]):
        _, _, _, back, option = layer[index]
        chosen.append(option)
        index = back
    chosen.reverse()

    by_night = {}
    filled = [w for w in windows if w["legal"]]
    for window, option in zip(filled, chosen, strict=True):
        by_night[window["night"]] = (window, option)

    positions = [0.0, *(o.along_m for o in chosen), length_m]
    choices = []
    for number, (window, option) in enumerate(by_night.values(), start=1):
        before, after = positions[number - 1], positions[number + 1]
        choices.append(
            _explain(window, option, (before, after), day_m, climb, settings, plan_night=number)
        )

    gaps = [_gap(w) for w in windows if not w["legal"]]
    return {
        "nights_requested": nights,
        "day_target_m": round(day_m, 1),
        "gain_target_m": round(day_gain, 1) if day_gain is not None else None,
        "choices": choices,
        "gaps": gaps,
        "cost": round(total_cost, 6),
    }


def _explain(window, option, neighbours, day_m, climb, settings, plan_night) -> dict:
    """Why `option` was chosen for its night, in a sentence and in fields. `neighbours`
    are the places the days either side start and end: the stops before and after it."""
    before_m, after_m = neighbours
    legal = window["legal"]
    span = f"between {mile_mark(window['start_m'])} and {mile_mark(window['end_m'])}"
    score = option.score
    # Only Permitted stops are chosen, so the verdict (shown beside the stop) isn't repeated.
    head = f"Score {score:.0f}" if score is not None else "No score yet"

    top = max(_score(o, settings) for o in legal)
    alternative = None
    if len(legal) == 1:
        why = f"the only legal stop {span}"
    elif _score(option, settings) >= top:
        why = f"the highest-scoring of {len(legal)} legal stops {span}"
    else:
        rival = next(o for o in legal if _score(o, settings) == top)
        alternative = {
            "id": rival.id,
            "name": rival.name,
            "score": rival.score,
            "day_before_m": round(rival.along_m - before_m, 1),
            "day_after_m": round(after_m - rival.along_m, 1),
        }
        why = (
            f"{len(legal)} legal stops {span}. {rival.name} scores higher "
            f"({_score(rival, settings):.0f}) "
            f"but would make the days either side {miles(rival.along_m - before_m)} and "
            f"{miles(after_m - rival.along_m)}, against {miles(option.along_m - before_m)} "
            f"and {miles(after_m - option.along_m)} here (an even day is {miles(day_m)})"
        )
        if climb is not None:
            rival_gain = climb.shown(before_m, rival.along_m)
            gain = climb.shown(before_m, option.along_m)
            even = climb.shown(0.0, climb.distances[-1]) * day_m / climb.distances[-1]
            why += (
                f"; the climb to it would be {feet(rival_gain)} against {feet(gain)} here "
                f"(an even day climbs {feet(even)})"
            )
    text = f"{head}: {why}."
    others = len(window["other"])
    if others:
        text += (
            f" {others} other site{'s' if others != 1 else ''} there "
            f"{'are' if others != 1 else 'is'} not confirmed legal, so "
            f"{'they were' if others != 1 else 'it was'} not considered."
        )
    return {
        "night": plan_night,
        "even_night": window["night"],
        "id": option.id,
        "name": option.name,
        "distance_along_m": round(option.along_m, 1),
        "score": option.score,
        "window_start_m": round(window["start_m"], 1),
        "window_end_m": round(window["end_m"], 1),
        "legal_options": len(legal),
        "other_options": others,
        "alternative": alternative,
        "reason": text,
    }


def _gap(window) -> dict:
    others = len(window["other"])
    message = (
        f"No legal stop between {mile_mark(window['start_m'])} and "
        f"{mile_mark(window['end_m'])} for night {window['night']}, so that night is left "
        "out and the days either side run together."
    )
    if others:
        message += (
            f" {others} site{'s' if others != 1 else ''} there "
            f"{'are' if others != 1 else 'is'} unverified or not confirmed legal; add one "
            "with + Night only after checking it yourself."
        )
    return {
        "night": window["night"],
        "from_m": round(window["start_m"], 1),
        "to_m": round(window["end_m"], 1),
        "unverified": others,
        "message": message,
    }


# --- from the database -------------------------------------------------------------------


def resolve_nights(length_m: float, name: str, nights, daily_target_m, settings) -> int:
    """The number of nights to plan, from exactly one of `nights` and `daily_target_m`.
    AutoPlanError for a bad value or a route too short for the request."""
    if (nights is None) == (daily_target_m is None):
        raise AutoPlanError("Give either a number of nights or a daily distance target.")
    if nights is not None:
        if isinstance(nights, bool) or not isinstance(nights, int):
            raise AutoPlanError("nights must be a whole number.")
        if not 1 <= nights <= plans.MAX_STOPS:
            raise AutoPlanError(f"Choose 1 to {plans.MAX_STOPS} nights.")
    else:
        if isinstance(daily_target_m, bool) or not isinstance(daily_target_m, int | float):
            raise AutoPlanError("daily_target_m must be a number of metres.")
        if not math.isfinite(daily_target_m) or daily_target_m < settings.min_day_m:
            raise AutoPlanError(f"Choose a daily target of at least {miles(settings.min_day_m)}.")
        nights = days_for_target(length_m, daily_target_m) - 1
        if nights == 0:
            raise AutoPlanError(
                f"{name} is {miles(length_m)}, about one day at {miles(daily_target_m)} a "
                "day, so it needs no overnight stop."
            )
        if nights > plans.MAX_STOPS:
            raise AutoPlanError(
                f"{name} would take more than {plans.MAX_STOPS} nights at "
                f"{miles(daily_target_m)} a day. Choose a longer daily target."
            )
    day_m = length_m / (nights + 1)
    if day_m < settings.min_day_m:
        raise AutoPlanError(
            f"{name} is {miles(length_m)}: {nights} night{'s' if nights != 1 else ''} would "
            f"make days of {miles(day_m)}, under the {miles(settings.min_day_m)} minimum. "
            "Choose fewer nights."
        )
    return nights


def gather(route, line_m, within_m: int, settings: Settings) -> tuple[list[Option], dict, dict]:
    """The mapped campsites along the route (as the trail list finds them) and the
    potential spots Find campsites already found (never a new search). Returns the
    options, the sites by id (for the worked-out plan), and what was considered."""
    with connection.cursor() as cursor:
        cursor.execute(
            CAMPSITES_ALONG_SQL,
            [route.geom_m.ewkt, line_m.ewkt, within_m, settings.max_sites + 1],
        )
        rows = cursor.fetchall()
    truncated = len(rows) > settings.max_sites
    rows = rows[: settings.max_sites]
    along_settings = route_config()["along"]
    rows = [
        (site_id, along)
        for site_id, _, along, from_line in rows
        if position_along(along, line_m.length, from_line, along_settings)["position"] == ALONG
    ]
    found = Campsite.objects.select_related("facts", "terrain").in_bulk([r[0] for r in rows])

    config = load_scoring_config()
    options, sites = [], {}
    for site_id, along in rows:
        site = found[site_id]
        result, legality, name = plans.assess(site, config)
        options.append(
            Option(
                id=site.source_id,
                along_m=float(along),
                permitted=legality["verdict"] == PERMITTED,
                score=result["score"],
                name=name["display_name"] or "Campsite",
                verdict_label=legality["label"],
            )
        )
        sites[site.source_id] = site

    cached = TrailCandidates().lookup(route.geom, {"within_m": within_m})
    candidates = cached.value["candidates"] if cached else []
    for candidate in candidates:
        stop = plans.CandidateStop(candidate["id"])
        _, legality, name = plans.assess(stop, config)
        options.append(
            Option(
                id=candidate["id"],
                along_m=float(candidate["distance_along_m"]),
                permitted=legality["verdict"] == PERMITTED,
                score=candidate.get("score"),
                name=name["display_name"],
                verdict_label=legality["label"],
            )
        )
        sites[candidate["id"]] = stop

    mapped = [o for o in options if not o.id.startswith(plans.CANDIDATE_PREFIX)]
    considered = {
        "within_m": within_m,
        "mapped": len(mapped),
        "mapped_permitted": sum(o.permitted for o in mapped),
        "mapped_truncated": truncated,
        "candidates_searched": cached is not None,
        "candidates": len(candidates) if cached else None,
        "candidates_permitted": sum(
            o.permitted for o in options if o.id.startswith(plans.CANDIDATE_PREFIX)
        ),
    }
    return options, sites, considered


def auto_plan(route, *, nights=None, daily_target_m=None, within_m: int = 500) -> dict:
    """Propose overnight stops along `route`, and work the plan out as the plan endpoints
    do (plans.build_plan), so it opens as a normal editable plan."""
    settings = load_settings()
    line_m, _ = stitch(route.geom)
    length = line_m.length
    nights = resolve_nights(length, route.name, nights, daily_target_m, settings)

    profile, _ = plans._profile(route)
    climb = None
    if profile:
        params, distances = profile["params"], profile["distance_m"]
        smoothed = smoothed_profile(profile["elevation_m"], params)

        def measure(start_m: float, end_m: float) -> float:
            return day_stats([start_m, end_m], distances, smoothed, params)[0]["gain_m"]

        climb = Climb.from_profile(distances, smoothed)
        climb.measure = measure

    options, sites, considered = gather(route, line_m, within_m, settings)
    solved = solve(length, options, nights, settings, climb)
    stop_ids = [choice["id"] for choice in solved["choices"]]
    worked = plans.build_plan(route, [sites[i] for i in stop_ids]) if stop_ids else None

    if not stop_ids:
        status = "none"
    elif solved["gaps"]:
        status = "partial"
    else:
        status = "ok"
    return {
        "status": status,
        "mode": "nights" if daily_target_m is None else "daily_target",
        "daily_target_m": daily_target_m,
        **{key: solved[key] for key in ("nights_requested", "day_target_m", "gain_target_m")},
        "nights_planned": len(stop_ids),
        "stop_ids": stop_ids,
        "choices": solved["choices"],
        "gaps": solved["gaps"],
        "considered": considered,
        "weights": settings.weights(),
        "climb_used": climb is not None,
        "plan": worked,
    }
