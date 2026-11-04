"""
Does the cached-mosaic elevation match the region's current graph (TM05-149)?

    python manage.py compare_graph_elevation adirondacks [--trips 50] [--seed 149]

The current graph's samples came from 3DEP's getSamples. This samples the cached 3DEP
mosaic at exactly the same points, without rebuilding anything, and compares:

1. **Elevations**, sample by sample: the median, 95th percentile and largest |difference|.
2. **Climb**: the region's total edge ascent, and each edge's.
3. **Routes**: `trips` seeded random trips on the largest connected piece, solved by
   Naismith time on both graphs: how many take the same edges, and how far the time moves.

The tolerances are `elevation_check` in routing.yml; docs/routing.md says why each is set
where it is. Nothing is written to the database.
"""

from __future__ import annotations

import random
import statistics
from collections import defaultdict
from dataclasses import dataclass

from django.contrib.gis.geos import MultiPoint, Point

from geodata.models import METRIC_SRID

from . import engine
from .build import config, rise_and_fall
from .models import TrailEdge


@dataclass
class EdgeRow:
    """One stored edge and what the mosaic says at its samples (None: no data there)."""

    id: int
    u: int
    v: int
    length_m: float
    factor: float
    u_xy: tuple[float, float]
    v_xy: tuple[float, float]
    old: list[float]
    new: list[float | None]


def load_rows(region: str, sampler) -> list[EdgeRow]:
    """The region's stored edges, each with the mosaic sampled at its stored samples.
    `sampler` is an elevation_source.MosaicSampler; its fallback is switched off, so a
    point the mosaic lacks stays None instead of going to 3DEP."""
    sampler.fallback = None
    rows, points, slices = [], [], []
    edges = TrailEdge.objects.filter(region=region).exclude(kind=TrailEdge.Kind.BRIDGE)
    for edge in edges.only(
        "id", "start_node", "end_node", "length_m", "cost_factor", "samples", "geom_m"
    ):
        if not edge.samples:
            continue
        line = edge.geom_m
        start = len(points)
        points.extend(line.interpolate(d) for d, _ in edge.samples)
        rows.append(
            EdgeRow(
                edge.id,
                edge.start_node,
                edge.end_node,
                edge.length_m,
                edge.cost_factor,
                tuple(line.coords[0]),
                tuple(line.coords[-1]),
                [z for _, z in edge.samples],
                [],
            )
        )
        slices.append(slice(start, len(points)))
    values = []
    for offset in range(0, len(points), 5000):
        chunk = MultiPoint(points[offset : offset + 5000], srid=METRIC_SRID)
        chunk.transform(4326)
        values.extend(sampler([Point(p.x, p.y, srid=4326) for p in chunk])[0])
    for row, part in zip(rows, slices, strict=True):
        row.new = values[part]
    return rows


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, round(q / 100 * (len(ordered) - 1))))
    return ordered[k]


def _graph(rows: list[EdgeRow], use_new: bool) -> engine.Graph:
    coords, edges = {}, []
    for r in rows:
        coords[r.u], coords[r.v] = r.u_xy, r.v_xy
        z = (
            [n if n is not None else o for o, n in zip(r.old, r.new, strict=True)]
            if use_new
            else r.old
        )
        up, down = rise_and_fall(z) if len(z) > 1 else (0.0, 0.0)
        edges.append(engine.Edge(r.id, r.u, r.v, r.length_m, up, down, max(1.0, r.factor)))
    return engine.Graph(coords, edges)


def _largest_piece(rows: list[EdgeRow]) -> list[int]:
    adjacency = defaultdict(set)
    for r in rows:
        adjacency[r.u].add(r.v)
        adjacency[r.v].add(r.u)
    seen, best = set(), []
    for start in sorted(adjacency):
        if start in seen:
            continue
        piece, stack = [], [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            piece.append(node)
            for other in adjacency[node] - seen:
                seen.add(other)
                stack.append(other)
        if len(piece) > len(best):
            best = piece
    return sorted(best)


def compare(rows: list[EdgeRow], trips: int = 50, seed: int = 149) -> dict:
    """The comparison report for stored edges and their mosaic samples."""
    tolerance = config()["elevation_check"]
    diffs, nodata = [], 0
    old_total = new_total = 0.0
    edge_ascent_diffs = []
    for r in rows:
        for o, n in zip(r.old, r.new, strict=True):
            if n is None:
                nodata += 1
            else:
                diffs.append(abs(n - o))
        z = [n if n is not None else o for o, n in zip(r.old, r.new, strict=True)]
        old_up = rise_and_fall(r.old)[0] if len(r.old) > 1 else 0.0
        new_up = rise_and_fall(z)[0] if len(z) > 1 else 0.0
        old_total += old_up
        new_total += new_up
        edge_ascent_diffs.append(abs(new_up - old_up))

    old_graph, new_graph = _graph(rows, False), _graph(rows, True)
    nodes = _largest_piece(rows)
    rng = random.Random(seed)
    same, time_diffs, solved = 0, [], 0
    for _ in range(trips if len(nodes) > 1 else 0):
        start, end = rng.sample(nodes, 2)
        a = engine.route(old_graph, start, end, cost="naismith")
        b = engine.route(new_graph, start, end, cost="naismith")
        solved += 1
        same += [s.edge for s in a.steps] == [s.edge for s in b.steps]
        # Each route's time on the graph it was solved on.
        if a.naismith_s > 0:
            time_diffs.append(abs(b.naismith_s - a.naismith_s) / a.naismith_s * 100)

    total_pct = abs(new_total - old_total) / old_total * 100 if old_total else 0.0
    report = {
        "samples": len(diffs) + nodata,
        "samples_without_mosaic_data": nodata,
        "elevation_abs_diff_m": {
            "median": round(statistics.median(diffs), 2) if diffs else 0.0,
            "p95": round(percentile(diffs, 95), 2),
            "max": round(max(diffs), 2) if diffs else 0.0,
        },
        "total_ascent_m": {"previous": round(old_total, 1), "mosaic": round(new_total, 1)},
        "total_ascent_diff_pct": round(total_pct, 2),
        "edge_ascent_abs_diff_m_p95": round(percentile(edge_ascent_diffs, 95), 2),
        "trips": solved,
        "trips_same_edges": same,
        "trip_time_diff_pct": {
            "median": round(statistics.median(time_diffs), 2) if time_diffs else 0.0,
            "p95": round(percentile(time_diffs, 95), 2),
            "max": round(max(time_diffs), 2) if time_diffs else 0.0,
        },
    }
    checks = {
        "sample_median_m": report["elevation_abs_diff_m"]["median"] <= tolerance["sample_median_m"],
        "sample_p95_m": report["elevation_abs_diff_m"]["p95"] <= tolerance["sample_p95_m"],
        "total_ascent_pct": total_pct <= tolerance["total_ascent_pct"],
        "trip_time_p95_pct": report["trip_time_diff_pct"]["p95"] <= tolerance["trip_time_p95_pct"],
    }
    report["tolerance"] = dict(tolerance)
    report["checks"] = checks
    report["ok"] = all(checks.values())
    return report
