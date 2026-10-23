"""
Building the trail graph for a region (TM05-119). `build_trail_graph <region>` runs it.

1. **Cut.** Every way in the region whose node ids line up with its vertices is cut at
   each node it shares with another way (or with itself, for a loop), and at its ends.
   Each stretch between two cuts is an edge. Ways whose node ids do not line up are
   skipped and counted; ways that only cross without a shared node do not meet, as in
   OSM itself.
2. **Climb.** Each edge is sampled every `spacing_m` along its metre geometry (and at both
   ends), and the samples go to 3DEP in batches. Ascent is the sum of every rise between
   consecutive samples, descent every drop: at 50 m spacing that is already smoothed, and
   a per-edge threshold would lose the many small climbs of short edges. The samples are
   kept so a route can start partway along an edge. The raster is never stored.
3. **Store.** The region's edges are replaced in one transaction, with a TrailGraphBuild
   recording what was made and from what.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from django.contrib.gis.geos import LineString, MultiPoint, Point, Polygon
from django.db import transaction
from django.utils import timezone

from analysis.analyses.elevation import BATCH_SIZE, fetch_elevations, fill_gaps
from analysis.base import AnalysisError
from geodata.models import METRIC_SRID, Trail
from pipeline.regions import get_region

from .models import TrailEdge, TrailGraphBuild

SPACING_M = 50.0
#: Concurrent 3DEP requests. The service is public; a few at a time keeps a region build
#: to minutes without hammering it.
FETCH_WORKERS = 4


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


def _usable(way: Trail) -> bool:
    nodes = way.osm_node_ids or []
    return len(way.geom) == 1 and len(nodes) >= 2 and len(way.geom[0]) == len(nodes)


def cut_region(ways: list[Trail]) -> tuple[list[dict], int]:
    """The edges of a set of ways, without elevation, and how many ways were skipped."""
    usable = [way for way in ways if _usable(way)]
    shared = shared_nodes([way.osm_node_ids for way in usable])
    edges = []
    for way in usable:
        nodes = way.osm_node_ids
        metric = (way.geom_m or way.geom.transform(METRIC_SRID, clone=True))[0].coords
        wgs84 = way.geom[0].coords
        cuts = cut_points(nodes, shared)
        for i, j in zip(cuts, cuts[1:], strict=False):
            line_m = LineString(metric[i : j + 1], srid=METRIC_SRID)
            edges.append(
                {
                    "trail": way,
                    "name": (way.name or "").strip(),
                    "start_index": i,
                    "end_index": j,
                    "start_node": nodes[i],
                    "end_node": nodes[j],
                    "node_ids": list(nodes[i : j + 1]),
                    "line_m": line_m,
                    "geom": LineString(wgs84[i : j + 1], srid=4326),
                    "length_m": line_m.length,
                }
            )
    return edges, len(ways) - len(usable)


def _sample_points(edges: list[dict], spacing_m: float) -> tuple[list[Point], list[slice]]:
    """Every edge's sample points in EPSG:4326, and which slice of them is whose."""
    metric_points, slices = [], []
    for edge in edges:
        line = edge["line_m"]
        distances = sample_distances(edge["length_m"], spacing_m)
        edge["distances"] = distances
        start = len(metric_points)
        metric_points.extend(line.interpolate(d) for d in distances)
        slices.append(slice(start, len(metric_points)))
    points = []
    for offset in range(0, len(metric_points), 5000):
        chunk = MultiPoint(metric_points[offset : offset + 5000], srid=METRIC_SRID)
        chunk.transform(4326)
        points.extend(Point(p.x, p.y, srid=4326) for p in chunk)
    return points, slices


def _fetch_all(points: list[Point], fetch: Callable, workers: int) -> tuple[list, dict]:
    batches = [points[i : i + BATCH_SIZE] for i in range(0, len(points), BATCH_SIZE)]
    values: list[float | None] = []
    datasets: set[str] = set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for batch_values, source in pool.map(fetch, batches):
            values.extend(batch_values)
            datasets.update(source.get("datasets", []))
    return values, {"datasets": sorted(datasets)}


def climb(
    edges: list[dict],
    fetch: Callable = fetch_elevations,
    spacing_m: float = SPACING_M,
    workers: int = FETCH_WORKERS,
) -> dict:
    """Set ascent_m, descent_m and samples on every edge; return the provenance."""
    points, slices = _sample_points(edges, spacing_m)
    values, source = _fetch_all(points, fetch, workers)
    nodata = sum(1 for v in values if v is None)
    flat = 0
    for edge, part in zip(edges, slices, strict=True):
        raw = values[part]
        try:
            filled = fill_gaps(raw)
        except AnalysisError:
            filled, flat = [0.0] * len(raw), flat + 1  # no data at all: counted as flat
        edge["ascent_m"], edge["descent_m"] = rise_and_fall(filled)
        edge["samples"] = [
            [round(d, 1), round(z, 1)] for d, z in zip(edge["distances"], filled, strict=True)
        ]
    return {
        "source": "usgs-3dep",
        "spacing_m": spacing_m,
        "samples": len(points),
        "nodata": nodata,
        "edges_without_elevation": flat,
        **source,
    }


def build_region(
    region: str,
    fetch: Callable = fetch_elevations,
    spacing_m: float = SPACING_M,
    workers: int = FETCH_WORKERS,
    log=print,
) -> TrailGraphBuild:
    aoi = get_region(region)
    started, clock = timezone.now(), time.perf_counter()
    box = Polygon.from_bbox(aoi.bbox)
    box.srid = 4326
    ways = list(Trail.objects.filter(geom__intersects=box).order_by("pk"))
    edges, skipped = cut_region(ways)
    nodes = {e["start_node"] for e in edges} | {e["end_node"] for e in edges}
    log(f"{region}: {len(ways)} ways ({skipped} skipped), {len(edges)} edges, {len(nodes)} nodes")
    cut_s = time.perf_counter() - clock

    provenance = climb(edges, fetch, spacing_m, workers)
    climb_s = time.perf_counter() - clock - cut_s
    log(f"{region}: {provenance['samples']} elevation samples in {climb_s:.1f} s")

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
                    trail=e["trail"],
                    start_node=e["start_node"],
                    end_node=e["end_node"],
                    start_index=e["start_index"],
                    end_index=e["end_index"],
                    node_ids=e["node_ids"],
                    name=e["name"],
                    length_m=round(e["length_m"], 2),
                    ascent_m=round(e["ascent_m"], 2),
                    descent_m=round(e["descent_m"], 2),
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
            "timing_s": {
                "cut": round(cut_s, 1),
                "climb": round(climb_s, 1),
                "total": round(time.perf_counter() - clock, 1),
            },
        }
        build.save(update_fields=["finished_at", "provenance"])
    return build
