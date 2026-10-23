"""
The routing engine (TM05-119): shortest paths over the trail graph, in plain Python.

No Django, no database, no geometry library: a Graph is numbers in, a Route is numbers
out. That is the boundary a faster engine (a C++ one is planned) implements instead;
docs/routing.md specifies it. Everything that touches the database -- building the
graph, snapping clicks to it, turning a Route into a line on the map -- lives in
routing/graph.py and routing/service.py, on the far side of this interface.

    route(graph, start, end, waypoints=(), cost="naismith") -> Route

Nodes are integer ids; the graph uses OSM node ids, and negative ids for points added
between two junctions (a click in the middle of a trail). Each edge is walkable both
ways: `ascent_m` is the climb going u -> v and `descent_m` the drop, so the other way
round the two swap.

Costs:

    naismith   time in seconds by Naismith's rule: 5 km/h on the flat, plus one hour for
               every 600 m of ascent. Descent is free, as in the rule as Naismith gave it.
    distance   metres walked.

Either is multiplied by the edge's `factor` (1 for trail, more for a road walk, TM05-137),
so a route leaves trail only when that saves enough. A factor is never below 1.

The search is A* with a straight-line heuristic (distance divided by the flat speed for
naismith), which never overestimates, so the answer is the true least-cost path.
"""

from __future__ import annotations

import heapq
import math
from collections import ChainMap
from dataclasses import dataclass, field

FLAT_SPEED_M_PER_S = 5000 / 3600  # Naismith: 5 km/h
SECONDS_PER_M_ASCENT = 3600 / 600  # Naismith: one hour per 600 m of ascent
COSTS = ("naismith", "distance")


class RoutingError(ValueError):
    """The request cannot be routed: a node the graph does not have, or a cost it does
    not know."""


class NoRoute(RoutingError):
    """Two points the trail network does not connect."""

    def __init__(self, start: int, end: int):
        super().__init__(f"No connected trail path from node {start} to node {end}.")
        self.start, self.end = start, end


@dataclass(frozen=True)
class Edge:
    """One walkable piece of trail between two nodes. `id` is the caller's: the engine
    only hands it back in a Route."""

    id: int
    u: int
    v: int
    length_m: float
    ascent_m: float = 0.0
    descent_m: float = 0.0
    factor: float = 1.0

    def __post_init__(self):
        if self.factor < 1.0:
            raise RoutingError(f"Edge {self.id} has cost factor {self.factor}; it must be >= 1.")


@dataclass(frozen=True)
class Step:
    """An edge as walked: `forward` is u -> v."""

    edge: int
    forward: bool
    from_node: int
    to_node: int
    length_m: float
    ascent_m: float
    descent_m: float


@dataclass
class Leg:
    start: int
    end: int
    steps: list[Step] = field(default_factory=list)

    @property
    def length_m(self) -> float:
        return sum(step.length_m for step in self.steps)

    @property
    def ascent_m(self) -> float:
        return sum(step.ascent_m for step in self.steps)

    @property
    def descent_m(self) -> float:
        return sum(step.descent_m for step in self.steps)

    @property
    def naismith_s(self) -> float:
        return naismith_seconds(self.length_m, self.ascent_m)


@dataclass
class Route:
    """The answer: one leg per stretch between consecutive stops (start, each waypoint in
    the order given, end)."""

    cost: str
    legs: list[Leg]
    expanded: int = 0  # nodes settled by the search, for measuring

    @property
    def steps(self) -> list[Step]:
        return [step for leg in self.legs for step in leg.steps]

    @property
    def nodes(self) -> list[int]:
        """Every node visited, in order, the start included once."""
        out = [self.legs[0].start] if self.legs else []
        for step in self.steps:
            out.append(step.to_node)
        return out

    @property
    def length_m(self) -> float:
        return sum(leg.length_m for leg in self.legs)

    @property
    def ascent_m(self) -> float:
        return sum(leg.ascent_m for leg in self.legs)

    @property
    def descent_m(self) -> float:
        return sum(leg.descent_m for leg in self.legs)

    @property
    def naismith_s(self) -> float:
        return naismith_seconds(self.length_m, self.ascent_m)


def naismith_seconds(length_m: float, ascent_m: float) -> float:
    return length_m / FLAT_SPEED_M_PER_S + max(ascent_m, 0.0) * SECONDS_PER_M_ASCENT


class Graph:
    """Nodes with planar coordinates in metres (for the heuristic) and undirected edges."""

    def __init__(self, coords: dict[int, tuple[float, float]], edges: list[Edge]):
        self.coords = dict(coords)
        self.edges: dict[int, Edge] = {}
        self.adjacency: dict[int, list[tuple[int, Edge, bool]]] = {n: [] for n in self.coords}
        self.removed: set[int] = set()
        for edge in edges:
            self.add_edge(edge)

    def copy(self) -> Graph:
        """A copy that can take extra nodes and edges without touching this one, in O(1):
        each map is layered over this graph's (ChainMap), so a request's few extra nodes
        and edges never copy the region's ~100,000 (TM05-137). Adjacency lists are shared
        until add_edge or remove_edge replaces them."""
        twin = Graph.__new__(Graph)
        twin.coords = ChainMap({}, self.coords)
        twin.edges = ChainMap({}, self.edges)
        twin.adjacency = ChainMap({}, self.adjacency)
        twin.removed = set(self.removed)
        return twin

    def add_node(self, node: int, xy: tuple[float, float]) -> None:
        self.coords[node] = xy
        self.adjacency.setdefault(node, [])

    def add_edge(self, edge: Edge) -> None:
        for node in (edge.u, edge.v):
            if node not in self.coords:
                raise RoutingError(f"Edge {edge.id} uses node {node}, which has no coordinates.")
        self.edges[edge.id] = edge
        # New lists, never append: a copy() shares its lists with the graph it came from.
        self.adjacency[edge.u] = [*self.adjacency[edge.u], (edge.v, edge, True)]
        self.adjacency[edge.v] = [*self.adjacency[edge.v], (edge.u, edge, False)]

    def remove_edge(self, edge_id: int) -> None:
        if not self.has_edge(edge_id):
            raise KeyError(edge_id)
        edge = self.edges[edge_id]
        self.removed.add(edge_id)
        for node in (edge.u, edge.v):
            self.adjacency[node] = [a for a in self.adjacency[node] if a[1].id != edge_id]

    def has_edge(self, edge_id: int) -> bool:
        return edge_id in self.edges and edge_id not in self.removed

    def __contains__(self, node: int) -> bool:
        return node in self.coords

    @property
    def node_count(self) -> int:
        return len(self.coords)

    @property
    def edge_count(self) -> int:
        return len(self.edges) - len(self.removed)


def step_cost(edge: Edge, forward: bool, cost: str) -> float:
    length = edge.length_m
    if cost == "distance":
        return length * edge.factor
    ascent = edge.ascent_m if forward else edge.descent_m
    return naismith_seconds(length, ascent) * edge.factor


def _heuristic(graph: Graph, node: int, goal: int, cost: str) -> float:
    (x1, y1), (x2, y2) = graph.coords[node], graph.coords[goal]
    straight = math.hypot(x2 - x1, y2 - y1)
    return straight if cost == "distance" else straight / FLAT_SPEED_M_PER_S


def shortest_leg(graph: Graph, start: int, end: int, cost: str) -> tuple[Leg, int]:
    """The least-cost path from start to end, and how many nodes the search settled."""
    if start == end:
        return Leg(start, end), 0
    best = {start: 0.0}
    came: dict[int, tuple[int, Edge, bool]] = {}
    frontier = [(_heuristic(graph, start, end, cost), 0.0, start)]
    settled: set[int] = set()
    while frontier:
        _, so_far, node = heapq.heappop(frontier)
        if node in settled:
            continue
        if node == end:
            break
        settled.add(node)
        for neighbour, edge, forward in graph.adjacency[node]:
            if neighbour in settled:
                continue
            candidate = so_far + step_cost(edge, forward, cost)
            if candidate < best.get(neighbour, math.inf):
                best[neighbour] = candidate
                came[neighbour] = (node, edge, forward)
                estimate = candidate + _heuristic(graph, neighbour, end, cost)
                heapq.heappush(frontier, (estimate, candidate, neighbour))
    if end not in came:
        raise NoRoute(start, end)

    steps: list[Step] = []
    node = end
    while node != start:
        previous, edge, forward = came[node]
        steps.append(
            Step(
                edge=edge.id,
                forward=forward,
                from_node=previous,
                to_node=node,
                length_m=edge.length_m,
                ascent_m=edge.ascent_m if forward else edge.descent_m,
                descent_m=edge.descent_m if forward else edge.ascent_m,
            )
        )
        node = previous
    steps.reverse()
    return Leg(start, end, steps), len(settled)


def route(
    graph: Graph,
    start: int,
    end: int,
    waypoints: tuple[int, ...] | list[int] = (),
    cost: str = "naismith",
) -> Route:
    """The least-cost route from start to end through each waypoint in the order given.
    Each leg is solved on its own, so a route may walk a stretch twice (out and back)."""
    if cost not in COSTS:
        raise RoutingError(f"Unknown cost {cost!r}; expected one of {', '.join(COSTS)}.")
    stops = [start, *waypoints, end]
    for node in stops:
        if node not in graph:
            raise RoutingError(f"Node {node} is not on the trail graph.")
    legs, expanded = [], 0
    for a, b in zip(stops, stops[1:], strict=False):
        leg, settled = shortest_leg(graph, a, b, cost)
        legs.append(leg)
        expanded += settled
    return Route(cost=cost, legs=legs, expanded=expanded)
