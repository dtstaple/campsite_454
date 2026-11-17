"""
Campsite access difficulty from the nearest reachable trailhead (TM05-171).

Plain Python, like routing/engine.py: no Django and no database. One multi-source search
over the region's trail graph, started from every trailhead at once, finds for every node
the quickest walk (by Naismith time, road walks at their cost factor) from any trailhead,
and which trailhead it starts from. A campsite then reads its nearest node's answer, so a
whole region is one search, not one per site.

`classify()` turns a walk's distance, climb and time into easy, moderate or hard with a
one-line reason, by the limits in routing.yml's `access` section. A site no trailhead
connects to is "unknown": never a guessed class.

The database side (snapping trailheads and campsites, storing the result) is
routing/access_store.py, run by `manage.py compute_access <region>`.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from .engine import Graph, naismith_seconds, step_cost

EASY, MODERATE, HARD, UNKNOWN = "easy", "moderate", "hard", "unknown"
CLASSES = (EASY, MODERATE, HARD, UNKNOWN)
LABELS = {
    EASY: "Easy access",
    MODERATE: "Moderate access",
    HARD: "Hard access",
    UNKNOWN: "Access unknown",
}


@dataclass(frozen=True)
class Reach:
    """The quickest walk to a node from any trailhead, as walked."""

    trailhead: str
    length_m: float
    ascent_m: float
    cost: float  # the search's cost: Naismith seconds times each edge's factor

    @property
    def naismith_s(self) -> float:
        return naismith_seconds(self.length_m, self.ascent_m)


@dataclass(frozen=True)
class Access:
    access_class: str
    reason: str
    trailhead: str = ""
    distance_m: float | None = None
    gain_m: float | None = None
    time_s: float | None = None


def from_trailheads(graph: Graph, sources: dict[int, str]) -> dict[int, Reach]:
    """Node -> its quickest walk from any of `sources` (node -> trailhead name).

    Dijkstra from all sources at once, on the routing cost (Naismith, factor-weighted), so
    each node keeps the trailhead the planner itself would start from. Walking a trailhead
    -> site, ascent is the climb in the walking direction. Nodes no source reaches are
    absent. Ties break on the trailhead name, so the answer is deterministic."""
    best: dict[int, float] = {}
    reach: dict[int, Reach] = {}
    frontier: list[tuple[float, str, int, float, float]] = []
    for node, name in sources.items():
        if node in graph:
            heapq.heappush(frontier, (0.0, name, node, 0.0, 0.0))
    while frontier:
        cost, name, node, length, ascent = heapq.heappop(frontier)
        if node in reach:
            continue
        reach[node] = Reach(name, length, ascent, cost)
        for neighbour, edge, forward in graph.adjacency[node]:
            if neighbour in reach:
                continue
            candidate = cost + step_cost(edge, forward, "naismith")
            if candidate < best.get(neighbour, math.inf):
                best[neighbour] = candidate
                climb = edge.ascent_m if forward else edge.descent_m
                heapq.heappush(
                    frontier, (candidate, name, neighbour, length + edge.length_m, ascent + climb)
                )
    return reach


def _duration(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    if hours == 0:
        return f"{minutes} min"
    return f"{hours} h {minutes:02d} min" if minutes else f"{hours} h"


def _limits_text(limits: dict) -> str:
    return (
        f"{limits['distance_km']:g} km, {limits['gain_m']:g} m of climb "
        f"and {limits['time_h']:g} h of walking"
    )


def classify(
    distance_m: float, gain_m: float, time_s: float, trailhead: str, settings: dict
) -> Access:
    """Easy, moderate or hard: the first class in `settings['classes']` whose every limit
    the walk is within, else hard. The reason gives the walk and the limit it passed."""
    walk = (
        f"{distance_m / 1000:.1f} km and {round(gain_m)} m of climb "
        f"from {trailhead or 'a trailhead'}, "
        f"about {_duration(time_s)} by Naismith's rule"
    )
    classes = settings["classes"]
    for name in (EASY, MODERATE):
        limits = classes[name]
        if (
            distance_m <= limits["distance_km"] * 1000
            and gain_m <= limits["gain_m"]
            and time_s <= limits["time_h"] * 3600
        ):
            return Access(
                name,
                f"{walk}: within {_limits_text(limits)}.",
                trailhead,
                distance_m,
                gain_m,
                time_s,
            )
    return Access(
        HARD,
        f"{walk}: over the moderate limit of {_limits_text(classes[MODERATE])}.",
        trailhead,
        distance_m,
        gain_m,
        time_s,
    )


def unknown(reason: str) -> Access:
    return Access(UNKNOWN, reason)


def site_access(reach: Reach | None, approach_m: float | None, settings: dict) -> Access:
    """A campsite's access from its nearest graph node's Reach and the straight line from
    that node to the site (`approach_m`, walked flat). None for either is unknown."""
    if approach_m is None:
        return unknown(
            f"No trail within {settings['campsite_max_m']:g} m of this site, so how far it is "
            "from a trailhead is not known."
        )
    if reach is None:
        return unknown(
            "No trailhead connects to the trails near this site, so its access is not known."
        )
    distance = reach.length_m + approach_m
    time_s = naismith_seconds(distance, reach.ascent_m)
    return classify(distance, reach.ascent_m, time_s, reach.trailhead, settings)
