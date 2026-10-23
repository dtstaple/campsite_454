"""
Routes across connected trails (TM05-119, forgiving since TM05-137): the database side of
the router.

    plan(points, cost)  clicks on the map -> a PlannedRoute
    resolve(route_id)   a PlannedRoute again, from its id

A planned route is identified by what the user chose, not by a row:

    <region>:<cost>:<stop>,<stop>,...    e.g. adirondacks:naismith:w187512345-41230,2306094170

Each stop is where a click snapped, start first and end last:

- `w<way>-<decimetres>`: a point on OSM trail way <way>, that far from its first vertex.
  A click snaps to the nearest point on a trail segment, not just the nearest vertex.
- `<node>`: an OSM node id, for a stop exactly at a junction (and every TM05-119 id).

Both survive a graph rebuild, so a saved plan or a shared link re-solves to the same route
while the trails are unchanged. Re-solving is cheap (docs/routing.md), so nothing else is
stored.

The engine (routing/engine.py) only sees junctions. A stop between two junctions becomes
a node of its own for the one request: its edge is split there, with the length and
climb of each part taken from the edge's stored samples.

The result is an unsaved TrailRoute, like an assembled trail (TM05-97), so the route
detail, Find campsites, overnight plans and GPX treat it like any trail. Its `trails`
list says where it leaves trail: a "road walk", a "track", or a "gap bridged" where the
map leaves trails that meet unjoined (routing/build.py).
"""

from __future__ import annotations

import bisect
import hashlib
import math
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache

from django.contrib.gis.gdal import CoordTransform, SpatialReference
from django.contrib.gis.geos import LineString, MultiLineString, Point
from django.db import connection

from geodata.assembly import way_number
from geodata.models import METRIC_SRID, Connector, Trail, TrailRoute

from . import engine
from .build import config
from .models import TrailEdge, TrailGraphBuild

MAX_STOPS = 10
UNNAMED = "Unnamed path"
KIND_LABELS = {
    TrailEdge.Kind.TRAIL: "trail",
    TrailEdge.Kind.TRACK: "track",
    TrailEdge.Kind.ROAD: "road walk",
    TrailEdge.Kind.BRIDGE: "gap bridged",
}
UNNAMED_BY_KIND = {
    TrailEdge.Kind.TRAIL: UNNAMED,
    TrailEdge.Kind.TRACK: "Unnamed track",
    TrailEdge.Kind.ROAD: "Unnamed road",
    TrailEdge.Kind.BRIDGE: "Gap between mapped trails",
}
SNAPPABLE = (TrailEdge.Kind.TRAIL, TrailEdge.Kind.TRACK)
STOP = r"(?:w\d+-\d+|\d+)"
ROUTE_ID = re.compile(
    rf"^(?P<region>[a-z0-9-]+):(?P<cost>[a-z]+):(?P<stops>{STOP}(?:,{STOP}){{1,9}})$"
)
#: Within this many metres of an edge's end, a stop is that end's node.
AT_NODE_M = 0.5


def snapping() -> dict:
    return config()["snapping"]


@cache
def _to_metric() -> CoordTransform:
    """One transformation per process. `geom.transform(srid)` builds a new one each call,
    and setting PROJ up costs ~15 ms: that was most of a warm request (TM05-137)."""
    return CoordTransform(SpatialReference(4326), SpatialReference(METRIC_SRID))


@cache
def _to_wgs84() -> CoordTransform:
    return CoordTransform(SpatialReference(METRIC_SRID), SpatialReference(4326))


class PlanningError(ValueError):
    """A request the router cannot answer: shown to the user as given. `suggestion` is
    the nearest point from which a connected route exists, when one was found."""

    def __init__(self, message: str, suggestion: dict | None = None):
        super().__init__(message)
        self.suggestion = suggestion


@dataclass(frozen=True)
class Stop:
    token: str
    node: int  # the engine's node for it: an OSM node, or negative for a point on an edge
    lon: float
    lat: float
    trail_name: str
    snapped_m: float | None = None  # click -> trail, only when planned from a click


@dataclass(frozen=True)
class Placement:
    """Where on a stored edge a stop is: `along_m` from the edge's start."""

    edge: TrailEdge
    along_m: float


@dataclass
class PlannedRoute:
    id: str
    region: str
    cost: str
    stops: list[Stop]
    route: engine.Route
    trail_route: TrailRoute
    trails: list[dict]
    legs: list[dict]
    off_trail: dict = field(default_factory=dict)
    timing_ms: dict = field(default_factory=dict)


# --- the graph in memory ------------------------------------------------------------------


@dataclass
class RegionGraph:
    region: str
    build_id: int
    graph: engine.Graph
    loaded_ms: float
    #: Node -> the id of its connected piece of the network, and each piece's length.
    #: Mapped trails are many pieces (docs/routing.md): a click is snapped within one.
    component: dict[int, int] = field(default_factory=dict)
    component_length_m: dict[int, float] = field(default_factory=dict)


def components(graph: engine.Graph) -> dict[int, int]:
    """Node -> connected-piece id, by union-find over the edges."""
    parent = {node: node for node in graph.coords}

    def root(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for edge in graph.edges.values():
        a, b = root(edge.u), root(edge.v)
        if a != b:
            parent[a] = b
    return {node: root(node) for node in parent}


_graphs: dict[str, RegionGraph] = {}
_lock = threading.Lock()

EDGES_SQL = """
SELECT id, start_node, end_node, length_m, ascent_m, descent_m, cost_factor,
       ST_X(ST_StartPoint(geom_m)), ST_Y(ST_StartPoint(geom_m)),
       ST_X(ST_EndPoint(geom_m)), ST_Y(ST_EndPoint(geom_m))
FROM routing_trailedge WHERE region = %s
"""


def region_graph(region: str) -> tuple[RegionGraph, bool]:
    """The region's graph from its latest build, loaded once per process and reloaded
    when a newer build exists; and whether it was already loaded."""
    latest = (
        TrailGraphBuild.objects.filter(region=region, finished_at__isnull=False)
        .values_list("id", flat=True)
        .first()
    )
    if latest is None:
        raise PlanningError(f"No trail graph has been built for {region} yet.")
    cached = _graphs.get(region)
    if cached and cached.build_id == latest:
        return cached, True
    with _lock:
        cached = _graphs.get(region)
        if cached and cached.build_id == latest:
            return cached, True
        started = time.perf_counter()
        with connection.cursor() as cursor:
            cursor.execute(EDGES_SQL, [region])
            rows = cursor.fetchall()
        coords, edges = {}, []
        for eid, u, v, length, up, down, factor, ux, uy, vx, vy in rows:
            coords[u], coords[v] = (ux, uy), (vx, vy)
            edges.append(engine.Edge(eid, u, v, length, up, down, max(1.0, factor or 1.0)))
        graph = engine.Graph(coords, edges)
        piece = components(graph)
        lengths = defaultdict(float)
        for edge in edges:
            lengths[piece[edge.u]] += edge.length_m
        loaded = RegionGraph(
            region, latest, graph, (time.perf_counter() - started) * 1000, piece, dict(lengths)
        )
        _graphs[region] = loaded
        return loaded, False


def forget_graphs() -> None:
    """Drop every cached graph (tests, and measuring cold starts)."""
    _graphs.clear()


# --- placing a stop on an edge ------------------------------------------------------------


def _cumulative(coords) -> list[float]:
    out = [0.0]
    for a, b in zip(coords, coords[1:], strict=False):
        out.append(out[-1] + math.dist(a, b))
    return out


def _wgs_at(edge: TrailEdge, along_m: float) -> tuple[float, float]:
    """The lon/lat `along_m` metres along a stored edge."""
    along = _cumulative(edge.geom_m.coords)
    wgs = edge.geom.coords
    k = max(1, min(len(along) - 1, bisect.bisect_left(along, along_m)))
    span = along[k] - along[k - 1]
    t = 0.0 if span == 0 else (along_m - along[k - 1]) / span
    t = max(0.0, min(1.0, t))
    (x0, y0), (x1, y1) = wgs[k - 1], wgs[k]
    return x0 + t * (x1 - x0), y0 + t * (y1 - y0)


def _token(placement: Placement, way_source_id: str | None) -> tuple[str, int | None]:
    """The stop's id in a route id, and its node when it is exactly at a junction."""
    edge, along = placement.edge, placement.along_m
    if along <= AT_NODE_M:
        return str(edge.start_node), edge.start_node
    if along >= edge.length_m - AT_NODE_M:
        return str(edge.end_node), edge.end_node
    number = way_number(way_source_id or "")
    decimetres = round((edge.start_along_m + along) * 10)
    return f"w{number}-{decimetres}", None


def _stop(placement: Placement, way_source_id: str | None, nodes: dict, snapped_m=None) -> Stop:
    token, node = _token(placement, way_source_id)
    if node is None:
        node = nodes.setdefault(token, -(len(nodes) + 1))
    lon, lat = _wgs_at(placement.edge, placement.along_m)
    return Stop(
        token=token,
        node=node,
        lon=round(lon, 6),
        lat=round(lat, 6),
        trail_name=placement.edge.name or UNNAMED_BY_KIND[placement.edge.kind],
        snapped_m=snapped_m,
    )


# --- snapping clicks ----------------------------------------------------------------------


@dataclass
class Candidate:
    edge: TrailEdge
    distance_m: float
    along_m: float
    component: int


CANDIDATES_SQL = """
SELECT c.idx, e.id, ST_Distance(e.geom_m, c.g)
FROM unnest(%s::int[], %s::float8[], %s::float8[]) AS p(idx, x, y)
CROSS JOIN LATERAL (SELECT ST_SetSRID(ST_MakePoint(p.x, p.y), %s) AS g, p.idx) AS c
CROSS JOIN LATERAL (
    SELECT id, geom_m FROM routing_trailedge
    WHERE kind = ANY(%s) AND ST_DWithin(geom_m, c.g, %s)
    ORDER BY geom_m <-> c.g LIMIT %s
) AS e
ORDER BY c.idx, 3
"""


def _candidates(
    points: list[Point], radius_m: float, limit: int
) -> list[list[tuple[TrailEdge, float]]]:
    """Each click's nearest trail edges within `radius_m` and their distances, nearest
    first, in one query (index-ordered KNN per click)."""
    with connection.cursor() as cursor:
        cursor.execute(
            CANDIDATES_SQL,
            [
                list(range(len(points))),
                [p.x for p in points],
                [p.y for p in points],
                METRIC_SRID,
                list(SNAPPABLE),
                radius_m,
                limit,
            ],
        )
        hits = cursor.fetchall()
    rows = (
        TrailEdge.objects.select_related("trail")
        .only(*_EDGE_FIELDS, "trail__source_id")
        .in_bulk({edge_id for _, edge_id, _ in hits})
    )
    out: list[list[tuple[TrailEdge, float]]] = [[] for _ in points]
    for index, edge_id, distance in hits:
        out[index].append((rows[edge_id], distance))
    return out


# Not `samples`: only the edge a stop splits needs them, and it loads them on first use.
_EDGE_FIELDS = (
    "id",
    "region",
    "kind",
    "trail",
    "start_node",
    "end_node",
    "start_index",
    "end_index",
    "start_along_m",
    "node_ids",
    "name",
    "length_m",
    "geom",
    "geom_m",
)


def snap_all(clicks: list[tuple[float, float]]) -> tuple[str, list[Placement], list[float], dict]:
    """Each click's point on a trail, all on one connected piece of the network.

    Every click projects onto the nearest trail **segments** within `snapping.radius_m`
    (not just the nearest vertex) and keeps the nearest of each connected piece they lie
    in. The piece chosen is the one every click reaches, at the least total distance, where
    a piece with less than `fragment_max_km` of trail (a few paths round a lodge, say)
    counts `fragment_penalty_m` extra. So a click never snaps to a tiny isolated fragment
    when a main-network trail is nearby. When no piece is shared, PlanningError says where
    a connected route would start.

    Returns the region, each click's placement and snap distance, and the graph-load time.
    """
    settings = snapping()
    radius, limit = float(settings["radius_m"]), int(settings["candidates"])
    points = [Point(lon, lat, srid=4326).transform(_to_metric(), clone=True) for lon, lat in clicks]

    nearby = []
    region = None
    for (lon, lat), rows in zip(clicks, _candidates(points, radius, limit), strict=True):
        if region is not None:
            rows = [(row, d) for row, d in rows if row.region == region]
        if not rows:
            raise PlanningError(
                f"No mapped trail within {radius:.0f} m of {lat:.5f}, {lon:.5f}. "
                "Click closer to a trail."
            )
        region = region or rows[0][0].region
        nearby.append([(row, d) for row, d in rows if row.region == region])

    loading = time.perf_counter()
    loaded, was_cached = region_graph(region)
    load = {
        "graph_load": round((time.perf_counter() - loading) * 1000, 1),
        "graph_was_cached": was_cached,
    }
    piece = loaded.component
    fragment_m = float(settings["fragment_max_km"]) * 1000
    penalty = float(settings["fragment_penalty_m"])

    per_click: list[dict[int, Candidate]] = []
    for point, rows in zip(points, nearby, strict=True):
        best: dict[int, Candidate] = {}
        for row, distance in rows:  # nearest first
            key = piece.get(row.start_node)
            if key is None or key in best:
                continue
            best[key] = Candidate(row, distance, row.geom_m.project(point), key)
        per_click.append(best)

    def score(candidate: Candidate) -> float:
        small = loaded.component_length_m.get(candidate.component, 0.0) < fragment_m
        return candidate.distance_m + (penalty if small else 0.0)

    shared = set(per_click[0]).intersection(*per_click[1:])
    if not shared:
        raise _not_connected(loaded, clicks, points, per_click, score)
    key = min(shared, key=lambda k: sum(score(c[k]) for c in per_click))
    chosen = [c[key] for c in per_click]
    return (
        region,
        [Placement(c.edge, c.along_m) for c in chosen],
        [round(c.distance_m, 1) for c in chosen],
        load,
    )


def _not_connected(loaded: RegionGraph, clicks, points, per_click, score) -> PlanningError:
    """Why the clicks can't be joined, and the nearest point that would join them: the
    node of the second click's network nearest the first click (or of the first click's
    network nearest the second), whichever is closer."""
    best = [min(c.values(), key=score) for c in per_click]
    first, other = (
        best[0],
        next((b for b in best[1:] if b.component != best[0].component), best[-1]),
    )
    i = best.index(other)
    options = []
    coords = loaded.graph.coords
    # Move the start onto the other stop's network, or that stop onto the start's.
    for target, from_point, moves_start in (
        (other.component, points[0], True),
        (first.component, points[i], False),
    ):
        nodes = [n for n, c in loaded.component.items() if c == target]
        if not nodes:
            continue
        node = min(nodes, key=lambda n: math.dist(coords[n], (from_point.x, from_point.y)))
        options.append((math.dist(coords[node], (from_point.x, from_point.y)), node, moves_start))
    names = [first.edge.name or UNNAMED, other.edge.name or UNNAMED]
    message = (
        f"No connected trails or roads join {names[0]} and {names[1]}: on the mapped network "
        "they are separate."
    )
    if not options:
        return PlanningError(message)
    distance, node, moves_first = min(options)
    xy = loaded.graph.coords[node]
    where = Point(*xy, srid=METRIC_SRID).transform(_to_wgs84(), clone=True)
    edge = TrailEdge.objects.filter(region=loaded.region, node_ids__contains=[node]).first()
    name = (edge.name if edge else "") or "a trail"
    which = "start" if moves_first else "stop"
    suggestion = {
        "lon": round(where.x, 6),
        "lat": round(where.y, 6),
        "trail_name": name,
        "distance_m": round(distance),
        "instead_of": which,
    }
    return PlanningError(
        f"{message} The nearest place a connected route is possible is on {name} at "
        f"{where.y:.5f}, {where.x:.5f}, {distance / 1000:.1f} km from your {which}: try "
        "there.",
        suggestion,
    )


# --- resolving stops from a route id ------------------------------------------------------


def _placement_for(region: str, token: str) -> tuple[Placement, str | None]:
    if token.startswith("w"):
        number, decimetres = token[1:].split("-")
        along_way = int(decimetres) / 10
        edge = (
            TrailEdge.objects.filter(
                region=region,
                trail__source_id=f"way/{number}",
                start_along_m__lte=along_way + 0.05,
            )
            .select_related("trail")
            .order_by("-start_along_m")
            .first()
        )
        if edge is None or along_way > edge.start_along_m + edge.length_m + 0.05:
            raise PlanningError(f"Way {number} is not on the {region} trail graph any more.")
        return Placement(edge, max(0.0, min(edge.length_m, along_way - edge.start_along_m))), (
            edge.trail.source_id
        )
    node = int(token)
    edge = (
        TrailEdge.objects.filter(region=region, node_ids__contains=[node])
        .select_related("trail")
        .first()
    )
    if edge is None:
        raise PlanningError(f"Node {node} is not on the {region} trail graph any more.")
    index = edge.node_ids.index(node)
    along = _cumulative(edge.geom_m.coords)[index]
    return Placement(edge, along), edge.trail.source_id if edge.trail_id else None


# --- splitting an edge at a stop ----------------------------------------------------------


@dataclass(frozen=True)
class Piece:
    """What an engine edge stands for: a stored edge from `a_m` to `b_m` along it."""

    edge: int
    a_m: float
    b_m: float


def _elevation_at(samples: list[list[float]], along_m: float) -> float:
    distances = [s[0] for s in samples]
    k = bisect.bisect_left(distances, along_m)
    if k <= 0:
        return samples[0][1]
    if k >= len(samples):
        return samples[-1][1]
    (d0, z0), (d1, z1) = samples[k - 1], samples[k]
    t = 0.0 if d1 == d0 else (along_m - d0) / (d1 - d0)
    return z0 + t * (z1 - z0)


def _climb_between(samples: list[list[float]], a_m: float, b_m: float) -> tuple[float, float]:
    """Ascent and descent walking from a_m to b_m (a_m < b_m) along an edge."""
    if not samples:
        return 0.0, 0.0
    inner = [s for s in samples if a_m < s[0] < b_m]
    profile = [_elevation_at(samples, a_m), *(s[1] for s in inner), _elevation_at(samples, b_m)]
    up = sum(max(0.0, q - p) for p, q in zip(profile, profile[1:], strict=False))
    down = sum(max(0.0, p - q) for p, q in zip(profile, profile[1:], strict=False))
    return up, down


class _Overlay:
    """A request's copy of the graph with its stops added, and what each edge stands for."""

    def __init__(self, base: engine.Graph):
        self.graph = base.copy()
        self.pieces: dict[int, Piece] = {}
        self.rows: dict[int, TrailEdge] = {}
        self._next_id = -1

    def piece(self, engine_id: int) -> Piece:
        if engine_id in self.pieces:
            return self.pieces[engine_id]
        return Piece(engine_id, 0.0, math.inf)

    def insert(self, placement: Placement, node: int) -> None:
        """Make the point `placement` names a node, splitting whichever engine edge
        currently covers it."""
        edge = placement.edge
        self.rows[edge.id] = edge
        if node in self.graph:
            return
        along = placement.along_m
        covering = [(eid, p) for eid, p in self._pieces_of(edge) if p.a_m < along < p.b_m]
        if not covering:
            return
        eid, part = covering[0]
        old = self.graph.edges[eid]
        self.graph.remove_edge(eid)
        self.pieces.pop(eid, None)
        point = edge.geom_m.interpolate(along)
        self.graph.add_node(node, (point.x, point.y))
        for a, b, u, v in ((part.a_m, along, old.u, node), (along, part.b_m, node, old.v)):
            up, down = _climb_between(edge.samples, a, b)
            new_id = self._next_id
            self._next_id -= 1
            self.graph.add_edge(engine.Edge(new_id, u, v, b - a, up, down, old.factor))
            self.pieces[new_id] = Piece(edge.id, a, b)

    def _pieces_of(self, edge: TrailEdge) -> list[tuple[int, Piece]]:
        found = [(eid, p) for eid, p in self.pieces.items() if p.edge == edge.id]
        if self.graph.has_edge(edge.id):
            found.append((edge.id, Piece(edge.id, 0.0, edge.length_m)))
        return found


# --- planning and resolving ---------------------------------------------------------------


def route_id(region: str, cost: str, tokens: list[str]) -> str:
    return f"{region}:{cost}:{','.join(tokens)}"


def parse_route_id(value: str) -> tuple[str, str, list[str]]:
    match = ROUTE_ID.match(value or "")
    if not match:
        raise PlanningError(f"Not a planned route id: {value!r}.")
    if match["cost"] not in engine.COSTS:
        raise PlanningError(f"Unknown cost {match['cost']!r}.")
    return match["region"], match["cost"], match["stops"].split(",")


def plan(points: list, cost: str = "naismith") -> PlannedRoute:
    """A route through clicked points: [[lon, lat], ...], start first and end last."""
    if cost not in engine.COSTS:
        raise PlanningError(f"cost must be one of {', '.join(engine.COSTS)}.")
    if not isinstance(points, list) or not 2 <= len(points) <= MAX_STOPS:
        raise PlanningError(f"Give a start, an end and up to {MAX_STOPS - 2} stops between.")
    started = time.perf_counter()
    clicks = []
    for point in points:
        try:
            clicks.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError, IndexError):
            raise PlanningError("Each point is [lon, lat].") from None
    region, placements, distances, load = snap_all(clicks)
    virtual: dict[str, int] = {}
    stops = [
        _stop(p, p.edge.trail.source_id if p.edge.trail_id else None, virtual, d)
        for p, d in zip(placements, distances, strict=True)
    ]
    snap_ms = (time.perf_counter() - started) * 1000 - load["graph_load"]
    planned = _solve(region, cost, stops, placements)
    # The graph was loaded while snapping; _solve found it cached.
    planned.timing_ms = {**planned.timing_ms, "snap": round(snap_ms, 1), **load}
    return planned


def resolve(value: str) -> PlannedRoute:
    """The planned route a route id stands for, solved again."""
    region, cost, tokens = parse_route_id(value)
    virtual: dict[str, int] = {}
    stops, placements = [], []
    for token in tokens:
        placement, source_id = _placement_for(region, token)
        stops.append(_stop(placement, source_id, virtual))
        placements.append(placement)
    return _solve(region, cost, stops, placements)


def _solve(region: str, cost: str, stops: list[Stop], placements: list[Placement]) -> PlannedRoute:
    started = time.perf_counter()
    loaded, was_cached = region_graph(region)
    load_ms = (time.perf_counter() - started) * 1000
    overlay = _Overlay(loaded.graph)
    for stop, placement in zip(stops, placements, strict=True):
        overlay.insert(placement, stop.node)
    nodes = [stop.node for stop in stops]
    searched = time.perf_counter()
    try:
        found = engine.route(overlay.graph, nodes[0], nodes[-1], nodes[1:-1], cost)
    except engine.NoRoute as error:
        names = {stop.node: stop.trail_name for stop in stops}
        raise PlanningError(
            f"The trails don't connect {names[error.start]} to {names[error.end]}: no mapped "
            "trail or road joins them. Try a stop on a trail between them."
        ) from error
    search_ms = (time.perf_counter() - searched) * 1000
    assembled = time.perf_counter()
    trail_route, trails, legs, off_trail = _assemble(found, overlay, stops, region, cost)
    planned = PlannedRoute(
        id=route_id(region, cost, [stop.token for stop in stops]),
        region=region,
        cost=cost,
        stops=stops,
        route=found,
        trail_route=trail_route,
        trails=trails,
        legs=legs,
        off_trail=off_trail,
    )
    planned.timing_ms = {
        "graph_load": round(load_ms, 1),
        "graph_was_cached": was_cached,
        "search": round(search_ms, 1),
        "assemble": round((time.perf_counter() - assembled) * 1000, 1),
        "nodes_settled": found.expanded,
    }
    return planned


def _part(row: TrailEdge, a_m: float, b_m: float) -> list[tuple[float, float]]:
    """The lon/lat line of a stored edge from a_m to b_m along it. A whole edge is its own
    line; only a stop's split edge needs distances along it."""
    if a_m <= 0 and b_m >= row.length_m - 1e-6:
        return list(row.geom.coords)
    along = _cumulative(row.geom_m.coords)
    b_m = min(b_m, along[-1])
    inner = [c for c, d in zip(row.geom.coords, along, strict=True) if a_m < d < b_m]
    return [_wgs_at(row, a_m), *inner, _wgs_at(row, b_m)]


def _assemble(found: engine.Route, overlay: _Overlay, stops, region, cost):
    stored_ids = {overlay.piece(step.edge).edge for step in found.steps}
    missing = stored_ids - set(overlay.rows)
    # Edges walked end to end need only their line: no samples, node ids or metre geometry.
    overlay.rows.update(
        TrailEdge.objects.only(
            "id", "kind", "name", "trail", "connector", "length_m", "geom"
        ).in_bulk(list(missing))
    )
    rows = overlay.rows.values()
    sources = dict(
        Trail.objects.filter(pk__in={r.trail_id for r in rows if r.trail_id}).values_list(
            "pk", "source_id"
        )
    )
    road_names = dict(
        Connector.objects.filter(pk__in={r.connector_id for r in rows if r.connector_id})
        .exclude(name="")
        .values_list("pk", "name")
    )

    coords: list[tuple[float, float]] = []
    by_key: dict[tuple[str, str], float] = {}
    order: list[tuple[str, str]] = []
    way_ids: list[int] = []
    off_trail = {"road_walk_m": 0.0, "track_m": 0.0, "bridged_m": 0.0}
    for step in found.steps:
        piece = overlay.piece(step.edge)
        row = overlay.rows[piece.edge]
        part = _part(row, piece.a_m, piece.b_m)
        if not step.forward:
            part.reverse()
        coords.extend(part if not coords else part[1:])
        name = row.name or road_names.get(row.connector_id) or UNNAMED_BY_KIND[row.kind]
        key = (name, row.kind)
        if key not in by_key:
            order.append(key)
        by_key[key] = by_key.get(key, 0.0) + step.length_m
        if row.kind == TrailEdge.Kind.ROAD:
            off_trail["road_walk_m"] += step.length_m
        elif row.kind == TrailEdge.Kind.TRACK:
            off_trail["track_m"] += step.length_m
        elif row.kind == TrailEdge.Kind.BRIDGE:
            off_trail["bridged_m"] += step.length_m
        number = way_number(sources.get(row.trail_id, "")) if row.trail_id else None
        if number is not None and number not in way_ids:
            way_ids.append(number)
    if len(coords) < 2:
        raise PlanningError("Start and end are the same point. Pick two different places.")

    line = LineString(coords, srid=4326)
    geom = MultiLineString([line], srid=4326)
    named = [n for n, kind in order if kind in SNAPPABLE and n not in UNNAMED_BY_KIND.values()]
    main = sorted(set(named), key=lambda n: -sum(v for (m, _), v in by_key.items() if m == n))[:2]
    title = " and ".join(main) if main else UNNAMED
    route = TrailRoute(
        source=TrailRoute.Source.OSM,
        source_id=f"planned/{_digest(region, cost, stops)}",
        osm_id=None,
        name=f"Route via {title}",
        geom=geom,
        length_m=found.length_m,
        member_way_ids=way_ids,
    )
    route.geom_m = geom.transform(_to_metric(), clone=True)
    trails = [
        {"name": name, "kind": KIND_LABELS[kind], "length_m": round(by_key[(name, kind)], 1)}
        for name, kind in order
    ]
    legs = [
        {
            "from": stops[i].trail_name,
            "to": stops[i + 1].trail_name,
            "length_m": round(leg.length_m, 1),
            "ascent_m": round(leg.ascent_m, 1),
            "descent_m": round(leg.descent_m, 1),
            "naismith_s": round(leg.naismith_s),
        }
        for i, leg in enumerate(found.legs)
    ]
    return route, trails, legs, {k: round(v, 1) for k, v in off_trail.items()}


def _digest(region, cost, stops) -> str:
    text = route_id(region, cost, [stop.token for stop in stops])
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def summary(planned: PlannedRoute) -> dict:
    """The `planned` block of the route detail: what was asked and what the graph says."""
    found = planned.route
    return {
        "id": planned.id,
        "region": planned.region,
        "cost": planned.cost,
        "stops": [
            {
                "token": s.token,
                "node_id": s.node if s.node > 0 else None,
                "lon": s.lon,
                "lat": s.lat,
                "trail_name": s.trail_name,
                "snapped_m": s.snapped_m,
            }
            for s in planned.stops
        ],
        "legs": planned.legs,
        "trails": planned.trails,
        "off_trail": planned.off_trail,
        "graph_totals": {
            "length_m": round(found.length_m, 1),
            "ascent_m": round(found.ascent_m, 1),
            "descent_m": round(found.descent_m, 1),
            "naismith_s": round(found.naismith_s),
        },
        "timing_ms": planned.timing_ms,
    }
