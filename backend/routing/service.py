"""
Routes across connected trails (TM05-119): the database side of the router.

    plan(points, cost)  clicks on the map -> a PlannedRoute
    resolve(route_id)   a PlannedRoute again, from its id

A planned route is identified by what the user chose, not by a row:

    <region>:<cost>:<node>,<node>,...      e.g. adirondacks:naismith:2306094170,...,2306094170

Each node is the OSM node id of the trail vertex a click snapped to: start, waypoints in
order, end. OSM node ids survive a graph rebuild, so a saved plan or a shared link
re-solves to the same route as long as the trails are unchanged. Re-solving is cheap
(docs/routing.md has the timings), which is why nothing else is stored.

The engine (routing/engine.py) only sees junctions. A stop between two junctions becomes
a node of its own for the one request: its edge is split there, with the length and
climb of each part taken from the edge's stored samples.

The result is an unsaved TrailRoute, like an assembled trail (TM05-97), so the route
detail, Find campsites, overnight plans and GPX treat it like any trail.
"""

from __future__ import annotations

import bisect
import hashlib
import math
import re
import threading
import time
from dataclasses import dataclass, field

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import LineString, MultiLineString, Point
from django.db import connection

from geodata.assembly import way_number
from geodata.models import METRIC_SRID, Trail, TrailRoute

from . import engine
from .models import TrailEdge, TrailGraphBuild

#: A click farther than this from every trail is not snapped.
MAX_SNAP_M = 400
MAX_STOPS = 10
UNNAMED = "Unnamed path"
ROUTE_ID = re.compile(r"^(?P<region>[a-z0-9-]+):(?P<cost>[a-z]+):(?P<nodes>\d+(?:,\d+){1,9})$")


class PlanningError(ValueError):
    """A request the router cannot answer: shown to the user as given."""


@dataclass(frozen=True)
class Stop:
    node: int
    lon: float
    lat: float
    trail_name: str
    snapped_m: float | None = None  # click -> vertex, only when planned from a click


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
    timing_ms: dict = field(default_factory=dict)


# --- the graph in memory ------------------------------------------------------------------


@dataclass
class RegionGraph:
    region: str
    build_id: int
    graph: engine.Graph
    loaded_ms: float
    #: Node -> the id of its connected piece of the network. Mapped trails are far from
    #: one network: the Adirondacks have about 5,000 pieces, most of them a few paths
    #: around a lodge or a campground, so a click is snapped within one piece (snap_all).
    component: dict[int, int] = field(default_factory=dict)


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
SELECT id, start_node, end_node, length_m, ascent_m, descent_m,
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
        for eid, u, v, length, up, down, ux, uy, vx, vy in rows:
            coords[u], coords[v] = (ux, uy), (vx, vy)
            edges.append(engine.Edge(eid, u, v, length, up, down))
        graph = engine.Graph(coords, edges)
        loaded = RegionGraph(
            region, latest, graph, (time.perf_counter() - started) * 1000, components(graph)
        )
        _graphs[region] = loaded
        return loaded, False


def forget_graphs() -> None:
    """Drop every cached graph (tests, and measuring cold starts)."""
    _graphs.clear()


# --- snapping ------------------------------------------------------------------------------


#: How many nearby edges each click considers when choosing the connected piece.
SNAP_CANDIDATES = 40


def _nearby_edges(lon: float, lat: float, region: str | None) -> tuple[Point, list[TrailEdge]]:
    point = Point(lon, lat, srid=4326).transform(METRIC_SRID, clone=True)
    edges = TrailEdge.objects.all() if region is None else TrailEdge.objects.filter(region=region)
    near = list(
        edges.filter(geom_m__dwithin=(point, MAX_SNAP_M))
        .annotate(distance=Distance("geom_m", point))
        .order_by("distance")[:SNAP_CANDIDATES]
    )
    if not near:
        raise PlanningError(
            f"No mapped trail within {MAX_SNAP_M} m of {lat:.5f}, {lon:.5f}. "
            "Click closer to a trail."
        )
    return point, near


def _vertex_stop(point: Point, edge: TrailEdge) -> Stop:
    metric = edge.geom_m.coords
    index = min(range(len(metric)), key=lambda i: math.dist(metric[i], (point.x, point.y)))
    x, y = edge.geom.coords[index]
    return Stop(
        node=edge.node_ids[index],
        lon=round(x, 6),
        lat=round(y, 6),
        trail_name=edge.name or UNNAMED,
        snapped_m=round(math.dist(metric[index], (point.x, point.y)), 1),
    )


def snap_all(clicks: list[tuple[float, float]]) -> tuple[str, list[tuple[Stop, TrailEdge]], dict]:
    """Each click's trail vertex, all on one connected piece of the network.

    The nearest vertex alone is not enough: at Adirondak Loj the nearest paths are a dozen
    footways around the lodge that join nothing else. So every click lists the edges within
    MAX_SNAP_M; the piece chosen is the one every click has an edge in, with the least
    total distance; and each click snaps to its nearest vertex on that piece. Also returns
    how long loading the graph took, which a cold request spends here.
    """
    first, near = _nearby_edges(*clicks[0], None)
    region = near[0].region
    nearby = [(first, [e for e in near if e.region == region])]
    nearby += [_nearby_edges(lon, lat, region) for lon, lat in clicks[1:]]
    loading = time.perf_counter()
    loaded, was_cached = region_graph(region)
    load = {
        "graph_load": round((time.perf_counter() - loading) * 1000, 1),
        "graph_was_cached": was_cached,
    }
    piece = loaded.component

    best: dict[int, list[TrailEdge]] = {}
    for _, edges in nearby:
        closest: dict[int, TrailEdge] = {}
        for edge in edges:  # nearest first
            closest.setdefault(piece.get(edge.start_node), edge)
        for key, edge in closest.items():
            best.setdefault(key, []).append(edge)
    shared = {key: edges for key, edges in best.items() if len(edges) == len(clicks)}
    if not shared:
        names = [edges[0].name or UNNAMED for _, edges in nearby]
        raise PlanningError(
            f"No connected trails join these points: {' / '.join(names)} don't meet on the "
            f"mapped network within {MAX_SNAP_M} m of where you clicked. Try points on "
            "trails that join."
        )
    key = min(shared, key=lambda k: sum(e.distance.m for e in shared[k]))
    return (
        region,
        [
            (_vertex_stop(point, edge), edge)
            for (point, _), edge in zip(nearby, shared[key], strict=True)
        ],
        load,
    )


def _edge_with_node(region: str, node: int) -> tuple[TrailEdge, int]:
    edge = TrailEdge.objects.filter(region=region, node_ids__contains=[node]).first()
    if edge is None:
        raise PlanningError(f"Node {node} is not on the {region} trail graph any more.")
    return edge, edge.node_ids.index(node)


# --- splitting an edge at a stop ----------------------------------------------------------


@dataclass(frozen=True)
class Piece:
    """What an engine edge stands for: part of a stored edge, vertex i to vertex j."""

    edge: int
    i: int
    j: int


def _cumulative(coords) -> list[float]:
    out = [0.0]
    for a, b in zip(coords, coords[1:], strict=False):
        out.append(out[-1] + math.dist(a, b))
    return out


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
        return self.pieces.get(engine_id) or Piece(engine_id, 0, -1)

    def insert(self, edge: TrailEdge, index: int, node: int) -> None:
        """Make vertex `index` of stored edge `edge` a node, splitting whichever engine
        edge currently covers it."""
        self.rows[edge.id] = edge
        if node in self.graph:
            return
        last = len(edge.node_ids) - 1
        covering = [(eid, p) for eid, p in self._pieces_of(edge.id, last) if p.i < index < p.j]
        if not covering:
            return
        eid, part = covering[0]
        metric = edge.geom_m.coords
        along = _cumulative(metric)
        old = self.graph.edges[eid]
        self.graph.remove_edge(eid)
        self.pieces.pop(eid, None)
        self.graph.add_node(node, metric[index])
        for i, j, u, v in ((part.i, index, old.u, node), (index, part.j, node, old.v)):
            up, down = _climb_between(edge.samples, along[i], along[j])
            new_id = self._next_id
            self._next_id -= 1
            self.graph.add_edge(engine.Edge(new_id, u, v, along[j] - along[i], up, down))
            self.pieces[new_id] = Piece(edge.id, i, j)

    def _pieces_of(self, stored_id: int, last: int) -> list[tuple[int, Piece]]:
        found = [(eid, p) for eid, p in self.pieces.items() if p.edge == stored_id]
        if stored_id in self.graph.edges:
            found.append((stored_id, Piece(stored_id, 0, last)))
        return found


# --- planning and resolving ---------------------------------------------------------------


def route_id(region: str, cost: str, nodes: list[int]) -> str:
    return f"{region}:{cost}:{','.join(str(n) for n in nodes)}"


def parse_route_id(value: str) -> tuple[str, str, list[int]]:
    match = ROUTE_ID.match(value or "")
    if not match:
        raise PlanningError(f"Not a planned route id: {value!r}.")
    if match["cost"] not in engine.COSTS:
        raise PlanningError(f"Unknown cost {match['cost']!r}.")
    return match["region"], match["cost"], [int(n) for n in match["nodes"].split(",")]


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
    region, snapped, load = snap_all(clicks)
    stops = [stop for stop, _ in snapped]
    rows = [(edge, edge.node_ids.index(stop.node)) for stop, edge in snapped]
    snap_ms = (time.perf_counter() - started) * 1000 - load["graph_load"]
    planned = _solve(region, cost, stops, rows)
    # The graph was loaded while snapping; _solve found it cached.
    planned.timing_ms = {**planned.timing_ms, "snap": round(snap_ms, 1), **load}
    return planned


def resolve(value: str) -> PlannedRoute:
    """The planned route a route id stands for, solved again."""
    region, cost, nodes = parse_route_id(value)
    stops, rows = [], []
    for node in nodes:
        edge, index = _edge_with_node(region, node)
        x, y = edge.geom.coords[index]
        stops.append(Stop(node, round(x, 6), round(y, 6), edge.name or UNNAMED))
        rows.append((edge, index))
    return _solve(region, cost, stops, rows)


def _solve(region: str, cost: str, stops: list[Stop], rows: list) -> PlannedRoute:
    started = time.perf_counter()
    loaded, was_cached = region_graph(region)
    load_ms = (time.perf_counter() - started) * 1000
    overlay = _Overlay(loaded.graph)
    for stop, (edge, index) in zip(stops, rows, strict=True):
        overlay.insert(edge, index, stop.node)
    nodes = [stop.node for stop in stops]
    searched = time.perf_counter()
    try:
        found = engine.route(overlay.graph, nodes[0], nodes[-1], nodes[1:-1], cost)
    except engine.NoRoute as error:
        names = {stop.node: stop.trail_name for stop in stops}
        raise PlanningError(
            f"The trails don't connect {names[error.start]} to {names[error.end]}: no mapped "
            "path joins them. Try a stop on a trail between them."
        ) from error
    search_ms = (time.perf_counter() - searched) * 1000
    assembled = time.perf_counter()
    trail_route, trails, legs = _assemble(found, overlay, stops, region, cost)
    planned = PlannedRoute(
        id=route_id(region, cost, nodes),
        region=region,
        cost=cost,
        stops=stops,
        route=found,
        trail_route=trail_route,
        trails=trails,
        legs=legs,
    )
    planned.timing_ms = {
        "graph_load": round(load_ms, 1),
        "graph_was_cached": was_cached,
        "search": round(search_ms, 1),
        "assemble": round((time.perf_counter() - assembled) * 1000, 1),
        "nodes_settled": found.expanded,
    }
    return planned


def _assemble(found: engine.Route, overlay: _Overlay, stops, region, cost):
    stored_ids = {overlay.piece(step.edge).edge for step in found.steps}
    missing = stored_ids - set(overlay.rows)
    overlay.rows.update(TrailEdge.objects.in_bulk(list(missing)))
    sources = dict(
        Trail.objects.filter(pk__in={row.trail_id for row in overlay.rows.values()}).values_list(
            "pk", "source_id"
        )
    )

    coords: list[tuple[float, float]] = []
    by_name: dict[str, float] = {}
    order: list[str] = []
    way_ids: list[int] = []
    for step in found.steps:
        piece = overlay.piece(step.edge)
        row = overlay.rows[piece.edge]
        j = piece.j if piece.j >= 0 else len(row.node_ids) - 1
        part = list(row.geom.coords[piece.i : j + 1])
        if not step.forward:
            part.reverse()
        coords.extend(part if not coords else part[1:])
        name = row.name or UNNAMED
        if name not in by_name:
            order.append(name)
        by_name[name] = by_name.get(name, 0.0) + step.length_m
        number = way_number(sources.get(row.trail_id, ""))
        if number is not None and number not in way_ids:
            way_ids.append(number)
    if len(coords) < 2:
        raise PlanningError("Start and end are the same point. Pick two different places.")

    line = LineString(coords, srid=4326)
    geom = MultiLineString([line], srid=4326)
    named = [n for n in order if n != UNNAMED]
    main = sorted(named, key=lambda n: -by_name[n])[:2]
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
    route.geom_m = geom.transform(METRIC_SRID, clone=True)
    trails = [{"name": n, "length_m": round(by_name[n], 1)} for n in order]
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
    return route, trails, legs


def _digest(region, cost, stops) -> str:
    text = route_id(region, cost, [stop.node for stop in stops])
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
                "node_id": s.node,
                "lon": s.lon,
                "lat": s.lat,
                "trail_name": s.trail_name,
                "snapped_m": s.snapped_m,
            }
            for s in planned.stops
        ],
        "legs": planned.legs,
        "trails": planned.trails,
        "graph_totals": {
            "length_m": round(found.length_m, 1),
            "ascent_m": round(found.ascent_m, 1),
            "descent_m": round(found.descent_m, 1),
            "naismith_s": round(found.naismith_s),
        },
        "timing_ms": planned.timing_ms,
    }
