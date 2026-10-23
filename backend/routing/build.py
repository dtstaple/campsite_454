"""
Building the trail graph for a region (TM05-119, made forgiving in TM05-137).
`build_trail_graph <region>` runs it; backend/routing/routing.yml holds the settings.

1. **Ways.** The region's trail ways (`Trail`: kind `trail`, or `track` for
   highway=track) and the roads and sidewalks between them (`geodata.Connector`, kind
   `road`). A way is used only when its node ids line up with its vertices.
2. **Near-miss gaps.** OSM often leaves trails that obviously meet without a shared node.
   - A trail's loose end within `bridge_tolerance_m` of another trail gets a short
     **bridge** edge to the nearest point on it (a vertex, or a new point on a segment).
   - Two trails that **cross** without a shared node get one at the crossing, unless
     either is tagged as passing over or under (`no_crossing_tags`).

   New points get deterministic ids above SYNTHETIC_BASE (from their coordinates), so a
   rebuild gives them the same ids.
3. **Cut.** Every way is cut at each node another way (or the same way, a second time)
   uses, at its ends, and at every bridge end. Each stretch between cuts is an edge.
4. **Roads near trails only.** Road edges further than `connectors.max_from_trail_m` from
   the trail network, measured along the roads, are dropped. A road walk between two
   trails is then at most about twice that, at `connectors.cost_factor` times the cost.
5. **Climb.** Each edge is sampled every `sample_spacing_m` metres, and its ascent and
   descent are the sums of the rises and drops between samples. A way the previous build
   measured reuses that build's samples by distance along the way, so a rebuild only
   asks 3DEP about new ways. The raster is never stored.
6. **Store.** The region's edges are replaced in one transaction, with a TrailGraphBuild.
"""

from __future__ import annotations

import bisect
import heapq
import math
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml
from django.contrib.gis.geos import LineString, MultiPoint, Point, Polygon
from django.db import transaction
from django.utils import timezone

from analysis.analyses.elevation import BATCH_SIZE, fetch_elevations, fill_gaps
from analysis.base import AnalysisError
from geodata.models import METRIC_SRID, Connector, Trail
from pipeline.regions import get_region

from .models import TrailEdge, TrailGraphBuild

CONFIG_PATH = Path(__file__).with_name("routing.yml")
#: Ids of points the build adds (bridge ends, crossings) start here: far above any OSM
#: node id, and under 2**53 so they survive a JavaScript number.
SYNTHETIC_BASE = 5_000_000_000_000_000
#: Concurrent 3DEP requests. The service is public; a few at a time keeps a region build
#: to minutes without hammering it.
FETCH_WORKERS = 4
#: Grid cell for finding nearby segments, metres.
CELL_M = 50.0


@cache
def config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def build_settings() -> dict:
    return config()["build"]


SPACING_M = float(build_settings()["sample_spacing_m"])


# --- small pure pieces --------------------------------------------------------------------


def cut_points(node_ids: list[int], shared: set[int]) -> list[int]:
    """Vertex indices where a way is cut: its ends, and every node another way (or this
    way, a second time) also uses."""
    last = len(node_ids) - 1
    return [i for i, node in enumerate(node_ids) if i in (0, last) or node in shared]


def shared_nodes(ways: list[list[int]]) -> set[int]:
    """Nodes used more than once across all ways, counting repeats within one way."""
    uses = Counter(node for nodes in ways for node in nodes)
    return {node for node, count in uses.items() if count > 1}


def sample_distances(length_m: float, spacing_m: float = SPACING_M) -> list[float]:
    """0, spacing, 2 x spacing, ... and the end itself."""
    if length_m <= 0:
        return [0.0]
    steps = int(length_m // spacing_m)
    out = [i * spacing_m for i in range(steps + 1)]
    if length_m - out[-1] > 1e-6:
        out.append(length_m)
    return out


def rise_and_fall(elevations: list[float]) -> tuple[float, float]:
    ascent = sum(max(0.0, b - a) for a, b in zip(elevations, elevations[1:], strict=False))
    descent = sum(max(0.0, a - b) for a, b in zip(elevations, elevations[1:], strict=False))
    return ascent, descent


def synthetic_id(x: float, y: float) -> int:
    """A deterministic node id for a point the build adds, from its metre coordinates to
    the decimetre (EPSG:5070 x and y are both well under 10**7 m in the US)."""
    return SYNTHETIC_BASE + round(x * 10) * 100_000_000 + round(y * 10)


def cumulative(coords: list[tuple[float, float]]) -> list[float]:
    out = [0.0]
    for a, b in zip(coords, coords[1:], strict=False):
        out.append(out[-1] + math.dist(a, b))
    return out


def project(point, a, b) -> tuple[float, tuple[float, float], float]:
    """(t in [0, 1], the nearest point on segment ab, its distance from `point`)."""
    (px, py), (ax, ay), (bx, by) = point, a, b
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    t = 0.0 if span == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / span))
    nearest = (ax + t * dx, ay + t * dy)
    return t, nearest, math.dist(point, nearest)


def crossing(a, b, c, d) -> tuple[float, float, tuple[float, float]] | None:
    """Where segments ab and cd cross, strictly inside both: (t on ab, u on cd, point)."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denominator = r[0] * s[1] - r[1] * s[0]
    if abs(denominator) < 1e-12:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / denominator
    u = (qp[0] * r[1] - qp[1] * r[0]) / denominator
    if 1e-6 < t < 1 - 1e-6 and 1e-6 < u < 1 - 1e-6:
        return t, u, (a[0] + t * r[0], a[1] + t * r[1])
    return None


# --- ways ---------------------------------------------------------------------------------


@dataclass
class Way:
    kind: str  # TrailEdge.Kind
    record: object  # a Trail or a Connector
    name: str
    nodes: list[int]
    metric: list[tuple[float, float]]
    wgs84: list[tuple[float, float]]
    crossable: bool = True
    #: A service=driveway road: kept only where it meets a trail (load_ways).
    driveway: bool = False
    #: (segment index, t, node id, metric point): points to add before cutting.
    inserts: list[tuple[int, float, int, tuple[float, float]]] = field(default_factory=list)

    @property
    def is_trail(self) -> bool:
        return self.kind in (TrailEdge.Kind.TRAIL, TrailEdge.Kind.TRACK)

    def apply_inserts(self) -> None:
        """Add the inserted points as vertices, in order along the way."""
        if not self.inserts:
            return
        by_segment = defaultdict(list)
        for segment, t, node, point in self.inserts:
            by_segment[segment].append((t, node, point))
        nodes, metric, wgs84 = [self.nodes[0]], [self.metric[0]], [self.wgs84[0]]
        for i in range(len(self.nodes) - 1):
            (ax, ay), (bx, by) = self.wgs84[i], self.wgs84[i + 1]
            seen = set()
            for t, node, point in sorted(by_segment.get(i, [])):
                if node in seen or node in (self.nodes[i], self.nodes[i + 1]):
                    continue
                seen.add(node)
                nodes.append(node)
                metric.append(point)
                wgs84.append((ax + t * (bx - ax), ay + t * (by - ay)))
            nodes.append(self.nodes[i + 1])
            metric.append(self.metric[i + 1])
            wgs84.append(self.wgs84[i + 1])
        self.nodes, self.metric, self.wgs84, self.inserts = nodes, metric, wgs84, []


def _way(kind: str, record, tags: dict, no_crossing: list[str]) -> Way | None:
    nodes = list(record.osm_node_ids or [])
    if len(record.geom) != 1 or len(nodes) < 2 or len(record.geom[0]) != len(nodes):
        return None
    metric_geom = record.geom_m or record.geom.transform(METRIC_SRID, clone=True)
    return Way(
        kind=kind,
        record=record,
        name=(record.name or "").strip(),
        nodes=nodes,
        metric=list(metric_geom[0].coords),
        wgs84=list(record.geom[0].coords),
        crossable=not any(key in tags and tags[key] not in ("no", "0") for key in no_crossing),
    )


def load_ways(box: Polygon, settings: dict) -> tuple[list[Way], int]:
    """The region's usable ways, and how many were skipped."""
    no_crossing = settings.get("no_crossing_tags", [])
    ways, skipped = [], 0
    for trail in Trail.objects.filter(geom__intersects=box).order_by("pk"):
        kind = TrailEdge.Kind.TRACK if trail.trail_type == "track" else TrailEdge.Kind.TRAIL
        way = _way(kind, trail, (trail.raw or {}).get("tags") or {}, no_crossing)
        skipped += way is None
        if way:
            ways.append(way)
    trail_nodes = {node for way in ways for node in way.nodes}
    for road in Connector.objects.filter(geom__intersects=box).order_by("pk"):
        tags = (road.raw or {}).get("tags") or {}
        way = _way(TrailEdge.Kind.ROAD, road, tags, no_crossing)
        skipped += way is None
        if way is None:
            continue
        # A driveway is somebody's way in; it is walked only as a trail's own access from
        # the road, so one that meets no trail is left out.
        if tags.get("service") == "driveway" and not trail_nodes.intersection(way.nodes):
            continue
        ways.append(way)
    return ways, skipped


# --- near-miss gaps -----------------------------------------------------------------------


@dataclass(frozen=True)
class Bridge:
    """A short edge across a gap the map leaves: from a loose trail end to the nearest
    point on another trail."""

    from_node: int
    to_node: int
    from_point: tuple[float, float]
    to_point: tuple[float, float]
    length_m: float


def _segment_grid(ways: list[Way]) -> dict[tuple[int, int], list[tuple[int, int]]]:
    grid = defaultdict(list)
    for w, way in enumerate(ways):
        for i, (a, b) in enumerate(zip(way.metric, way.metric[1:], strict=False)):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for cx in range(int(x0 // CELL_M), int(x1 // CELL_M) + 1):
                for cy in range(int(y0 // CELL_M), int(y1 // CELL_M) + 1):
                    grid[(cx, cy)].append((w, i))
    return grid


def find_bridges(ways: list[Way], tolerance_m: float) -> tuple[list[Bridge], int]:
    """Bridges for loose trail ends near another trail, and crossings joined with a new
    shared node. Records the points to insert on the ways; returns the bridges and how
    many crossings were joined."""
    grid = _segment_grid(ways)
    # A trail end shared with any way (a road included) is a junction, not a loose end.
    uses = Counter(node for way in ways for node in way.nodes)

    joined = 0
    done_pairs = set()
    for segments in grid.values():
        for k, (w1, i1) in enumerate(segments):
            for w2, i2 in segments[k + 1 :]:
                if w1 == w2 or (w1, i1, w2, i2) in done_pairs:
                    continue
                done_pairs.add((w1, i1, w2, i2))
                a, b = ways[w1], ways[w2]
                # Crossings are joined between trails only: a road crossing a trail with
                # no shared node is usually a bridge or a culvert.
                if not (a.is_trail and b.is_trail and a.crossable and b.crossable):
                    continue
                if {a.nodes[i1], a.nodes[i1 + 1]} & {b.nodes[i2], b.nodes[i2 + 1]}:
                    continue
                hit = crossing(a.metric[i1], a.metric[i1 + 1], b.metric[i2], b.metric[i2 + 1])
                if hit is None:
                    continue
                t, u, point = hit
                node = synthetic_id(*point)
                a.inserts.append((i1, t, node, point))
                b.inserts.append((i2, u, node, point))
                joined += 1

    bridges = []
    for w, way in enumerate(ways):
        if not way.is_trail:
            continue
        for end in (0, len(way.nodes) - 1):
            node = way.nodes[end]
            if uses[node] > 1:
                continue  # already a junction
            point = way.metric[end]
            cx, cy = int(point[0] // CELL_M), int(point[1] // CELL_M)
            best = None
            for nx in (cx - 1, cx, cx + 1):
                for ny in (cy - 1, cy, cy + 1):
                    for w2, i2 in grid.get((nx, ny), []):
                        if w2 == w:
                            continue
                        other = ways[w2]
                        t, nearest, distance = project(
                            point, other.metric[i2], other.metric[i2 + 1]
                        )
                        if distance <= tolerance_m and (best is None or distance < best[0]):
                            best = (distance, w2, i2, t, nearest)
            if best is None:
                continue
            distance, w2, i2, t, nearest = best
            other = ways[w2]
            if t <= 1e-6 or math.dist(nearest, other.metric[i2]) < 1.0:
                target = other.nodes[i2]
                nearest = other.metric[i2]
            elif t >= 1 - 1e-6 or math.dist(nearest, other.metric[i2 + 1]) < 1.0:
                target = other.nodes[i2 + 1]
                nearest = other.metric[i2 + 1]
            else:
                target = synthetic_id(*nearest)
                other.inserts.append((i2, t, target, nearest))
            if target != node:
                bridges.append(Bridge(node, target, point, nearest, max(distance, 0.01)))
    return bridges, joined


# --- cutting ------------------------------------------------------------------------------


def cut_ways(ways: list[Way], forced: set[int]) -> list[dict]:
    """Edges from the ways: cut at shared nodes, ends, and `forced` nodes."""
    shared = shared_nodes([way.nodes for way in ways]) | forced
    edges = []
    for way in ways:
        along = cumulative(way.metric)
        cuts = cut_points(way.nodes, shared)
        for i, j in zip(cuts, cuts[1:], strict=False):
            line_m = LineString(way.metric[i : j + 1], srid=METRIC_SRID)
            edges.append(
                {
                    "way": way,
                    "kind": way.kind,
                    "name": way.name,
                    "start_index": i,
                    "end_index": j,
                    "start_node": way.nodes[i],
                    "end_node": way.nodes[j],
                    "node_ids": list(way.nodes[i : j + 1]),
                    "line_m": line_m,
                    "geom": LineString(way.wgs84[i : j + 1], srid=4326),
                    "length_m": along[j] - along[i],
                    "start_along_m": along[i],
                }
            )
    return edges


def cut_region(ways: list[Trail]) -> tuple[list[dict], int]:
    """The edges of a set of trail ways alone, without gaps or roads (kept for callers and
    tests that only need the cut), and how many ways were skipped."""
    usable = [w for w in (_way(TrailEdge.Kind.TRAIL, t, {}, []) for t in ways) if w]
    return cut_ways(usable, set()), len(ways) - len(usable)


def prune_roads(
    edges: list[dict], max_from_trail_m: float, seeds: set[int] = frozenset()
) -> list[dict]:
    """Drop road edges further than `max_from_trail_m` along the roads from a trail (or
    from a `seeds` node: where a bridge from a trail end lands on a road)."""
    trail_nodes = {
        e[k] for e in edges if e["kind"] != TrailEdge.Kind.ROAD for k in ("start_node", "end_node")
    }
    trail_nodes |= set(seeds)
    adjacency = defaultdict(list)
    for e in edges:
        if e["kind"] == TrailEdge.Kind.ROAD:
            adjacency[e["start_node"]].append((e["end_node"], e["length_m"]))
            adjacency[e["end_node"]].append((e["start_node"], e["length_m"]))
    best = {node: 0.0 for node in trail_nodes if node in adjacency}
    frontier = [(0.0, node) for node in best]
    heapq.heapify(frontier)
    while frontier:
        d, node = heapq.heappop(frontier)
        if d > best.get(node, math.inf) or d > max_from_trail_m:
            continue
        for other, length in adjacency[node]:
            if d + length < best.get(other, math.inf):
                best[other] = d + length
                heapq.heappush(frontier, (d + length, other))
    kept = []
    for e in edges:
        if e["kind"] != TrailEdge.Kind.ROAD:
            kept.append(e)
            continue
        reach = min(best.get(e["start_node"], math.inf), best.get(e["end_node"], math.inf))
        if reach + e["length_m"] <= max_from_trail_m:
            kept.append(e)
    return kept


def bridge_edges(bridges: list[Bridge]) -> list[dict]:
    out = []
    for bridge in bridges:
        line_m = LineString([bridge.from_point, bridge.to_point], srid=METRIC_SRID)
        out.append(
            {
                "way": None,
                "kind": TrailEdge.Kind.BRIDGE,
                "name": "",
                "start_index": 0,
                "end_index": 1,
                "start_node": bridge.from_node,
                "end_node": bridge.to_node,
                "node_ids": [bridge.from_node, bridge.to_node],
                "line_m": line_m,
                "geom": line_m.transform(4326, clone=True),
                "length_m": bridge.length_m,
                "start_along_m": 0.0,
            }
        )
    return out


# --- elevation ----------------------------------------------------------------------------


def previous_profiles(region: str, original_along: dict) -> dict[tuple[str, int], list]:
    """For each way the last build measured: (distance along the way, elevation) pairs.

    Rows from before TM05-137 have no `start_along_m`; their `start_index` is a vertex of
    the way as ingested, so the offset is read from `original_along`, the way's cumulative
    distances before this build added any points."""
    out = defaultdict(list)
    rows = TrailEdge.objects.filter(region=region).exclude(kind=TrailEdge.Kind.BRIDGE)
    for row in rows.values("trail_id", "connector_id", "start_index", "start_along_m", "samples"):
        key = ("trail", row["trail_id"]) if row["trail_id"] else ("road", row["connector_id"])
        if not row["samples"]:
            continue
        offset = row["start_along_m"]
        if row["start_index"] > 0 and not offset:
            along = original_along.get(key)
            if along is None or row["start_index"] >= len(along):
                continue
            offset = along[row["start_index"]]
        out[key].extend((offset + d, z) for d, z in row["samples"])
    return {key: sorted(points) for key, points in out.items()}


def _from_profile(profile: list[tuple[float, float]], along: float) -> float:
    distances = [p[0] for p in profile]
    k = bisect.bisect_left(distances, along)
    if k <= 0:
        return profile[0][1]
    if k >= len(profile):
        return profile[-1][1]
    (d0, z0), (d1, z1) = profile[k - 1], profile[k]
    return z0 if d1 == d0 else z0 + (along - d0) / (d1 - d0) * (z1 - z0)


def _key(edge: dict):
    way = edge["way"]
    if way is None:
        return None
    return ("trail", way.record.pk) if way.is_trail else ("road", way.record.pk)


def _fetch_all(points: list[Point], fetch: Callable, workers: int) -> tuple[list, dict]:
    batches = [points[i : i + BATCH_SIZE] for i in range(0, len(points), BATCH_SIZE)]
    values: list[float | None] = []
    datasets: set[str] = set()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for batch_values, source in pool.map(fetch, batches):
            values.extend(batch_values)
            datasets.update(source.get("datasets", []))
    return values, {"datasets": sorted(datasets)}


def climb(
    edges: list[dict],
    fetch: Callable = fetch_elevations,
    spacing_m: float = SPACING_M,
    workers: int = FETCH_WORKERS,
    profiles: dict | None = None,
) -> dict:
    """Set ascent_m, descent_m and samples on every edge; return the provenance. Ways in
    `profiles` (the previous build's) are read from it; the rest are asked of 3DEP."""
    profiles = profiles or {}
    to_fetch, slices, reused = [], [], 0
    for edge in edges:
        edge["distances"] = sample_distances(edge["length_m"], spacing_m)
        if edge["kind"] == TrailEdge.Kind.BRIDGE:
            continue
        profile = profiles.get(_key(edge))
        if profile:
            base = edge["start_along_m"]
            edge["elevations"] = [_from_profile(profile, base + d) for d in edge["distances"]]
            reused += 1
            continue
        start = len(to_fetch)
        to_fetch.extend(edge["line_m"].interpolate(d) for d in edge["distances"])
        slices.append((edge, slice(start, len(to_fetch))))

    points = []
    for offset in range(0, len(to_fetch), 5000):
        chunk = MultiPoint(to_fetch[offset : offset + 5000], srid=METRIC_SRID)
        chunk.transform(4326)
        points.extend(Point(p.x, p.y, srid=4326) for p in chunk)
    values, source = _fetch_all(points, fetch, workers) if points else ([], {"datasets": []})
    nodata = sum(1 for v in values if v is None)
    flat = 0
    for edge, part in slices:
        try:
            edge["elevations"] = fill_gaps(values[part])
        except AnalysisError:
            edge["elevations"], flat = [0.0] * (part.stop - part.start), flat + 1

    # A bridge takes its ends' elevations from the edges it joins.
    at_node = {}
    for edge in edges:
        if "elevations" in edge:
            at_node.setdefault(edge["start_node"], edge["elevations"][0])
            at_node.setdefault(edge["end_node"], edge["elevations"][-1])
    for edge in edges:
        if edge["kind"] == TrailEdge.Kind.BRIDGE:
            a = at_node.get(edge["start_node"], at_node.get(edge["end_node"], 0.0))
            b = at_node.get(edge["end_node"], a)
            edge["elevations"] = [
                a + (b - a) * d / max(edge["length_m"], 1e-9) for d in edge["distances"]
            ]

    for edge in edges:
        edge["ascent_m"], edge["descent_m"] = rise_and_fall(edge["elevations"])
        edge["samples"] = [
            [round(d, 1), round(z, 1)]
            for d, z in zip(edge["distances"], edge["elevations"], strict=True)
        ]
    return {
        "source": "usgs-3dep",
        "spacing_m": spacing_m,
        "samples": len(points),
        "nodata": nodata,
        "edges_without_elevation": flat,
        "edges_reusing_previous_samples": reused,
        **source,
    }


# --- the build ----------------------------------------------------------------------------


def build_region(
    region: str,
    fetch: Callable = fetch_elevations,
    spacing_m: float | None = None,
    workers: int = FETCH_WORKERS,
    log=print,
) -> TrailGraphBuild:
    settings = build_settings()
    connectors = config()["connectors"]
    spacing_m = float(spacing_m or settings["sample_spacing_m"])
    aoi = get_region(region)
    started, clock = timezone.now(), time.perf_counter()
    box = Polygon.from_bbox(aoi.bbox)
    box.srid = 4326

    ways, skipped = load_ways(box, settings)
    original_along = {
        ("trail" if way.is_trail else "road", way.record.pk): cumulative(way.metric) for way in ways
    }
    bridges, crossings = find_bridges(ways, float(settings["bridge_tolerance_m"]))
    for way in ways:
        way.apply_inserts()
    forced = {b.from_node for b in bridges} | {b.to_node for b in bridges}
    edges = cut_ways(ways, forced)
    cut = len(edges)
    landings = {b.to_node for b in bridges}
    edges = prune_roads(edges, float(connectors["max_from_trail_m"]), landings) + bridge_edges(
        bridges
    )
    nodes = {e["start_node"] for e in edges} | {e["end_node"] for e in edges}
    kinds = Counter(e["kind"] for e in edges)
    log(
        f"{region}: {len(ways)} ways ({skipped} skipped), {len(edges)} edges "
        f"({dict(kinds)}; {cut - (len(edges) - len(bridges))} far road edges dropped), "
        f"{len(nodes)} nodes, {len(bridges)} bridged gaps, {crossings} crossings joined"
    )
    cut_s = time.perf_counter() - clock

    provenance = climb(edges, fetch, spacing_m, workers, previous_profiles(region, original_along))
    climb_s = time.perf_counter() - clock - cut_s
    log(
        f"{region}: {provenance['samples']} new elevation samples in {climb_s:.1f} s "
        f"({provenance['edges_reusing_previous_samples']} edges reused the last build's)"
    )

    factor = float(connectors["cost_factor"])
    with transaction.atomic():
        TrailEdge.objects.filter(region=region).delete()
        build = TrailGraphBuild.objects.create(
            region=region,
            started_at=started,
            ways=len(ways),
            ways_skipped=skipped,
            nodes=len(nodes),
            edges=len(edges),
            elevation_samples=provenance["samples"],
            elevation_nodata=provenance["nodata"],
        )
        TrailEdge.objects.bulk_create(
            [
                TrailEdge(
                    build=build,
                    region=region,
                    kind=e["kind"],
                    trail=e["way"].record if e["way"] and e["way"].is_trail else None,
                    connector=e["way"].record if e["way"] and not e["way"].is_trail else None,
                    start_node=e["start_node"],
                    end_node=e["end_node"],
                    start_index=e["start_index"],
                    end_index=e["end_index"],
                    start_along_m=round(e["start_along_m"], 2),
                    node_ids=e["node_ids"],
                    name=e["name"],
                    length_m=round(e["length_m"], 2),
                    ascent_m=round(e["ascent_m"], 2),
                    descent_m=round(e["descent_m"], 2),
                    cost_factor=factor if e["kind"] == TrailEdge.Kind.ROAD else 1.0,
                    samples=e["samples"],
                    geom=e["geom"],
                )
                for e in edges
            ],
            batch_size=2000,
        )
        build.finished_at = timezone.now()
        build.provenance = {
            **provenance,
            "edge_kinds": dict(kinds),
            "bridged_gaps": len(bridges),
            "crossings_joined": crossings,
            "settings": {**settings, "connectors": connectors},
            "timing_s": {
                "cut": round(cut_s, 1),
                "climb": round(climb_s, 1),
                "total": round(time.perf_counter() - clock, 1),
            },
        }
        build.save(update_fields=["finished_at", "provenance"])
    return build
