"""
Storing campsite access difficulty (TM05-171): the database side of routing/access.py.

`compute_region(region)` loads the region's trail graph, joins every trailhead to its
nearest graph node, runs one search from all of them, joins every campsite to its nearest
point on an edge, and writes each campsite's class, reason and walk onto its CampsiteFacts
row. Precomputed by the pipeline (`compute_access <region>`, a `make data` /
`make refresh` step after enrichment), never per request. Sites without a facts row are
skipped: enrich_campsites makes them first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.contrib.gis.geos import Polygon
from django.db import connection, transaction

from enrichment.models import CampsiteFacts
from geodata.models import METRIC_SRID, Campsite, Landmark
from pipeline.regions import get_region

from . import access
from .build import config
from .models import TrailEdge
from .service import _climb_between, _to_metric, region_graph

ACCESS_FIELDS = (
    "access_class",
    "access_reason",
    "access_trailhead",
    "access_distance_m",
    "access_gain_m",
    "access_time_s",
)


def settings() -> dict:
    return config()["access"]


@dataclass
class Summary:
    region: str
    trailheads: int = 0
    trailheads_joined: int = 0
    campsites: int = 0
    by_class: dict[str, int] = field(default_factory=dict)


def _metric_points(rows) -> list[tuple[object, float, float]]:
    """(row, x, y) in the graph's metre projection, with one PROJ transformation."""
    transform = _to_metric()
    out = []
    for row in rows:
        point = row.geom.transform(transform, clone=True)
        out.append((row, point.x, point.y))
    return out


NEAREST_EDGE_SQL = """
SELECT p.idx, e.id, ST_Distance(e.geom_m, p.g), ST_LineLocatePoint(e.geom_m, p.g) * e.length_m
FROM (
    SELECT idx, ST_SetSRID(ST_MakePoint(x, y), %s) AS g
    FROM unnest(%s::int[], %s::float8[], %s::float8[]) AS u(idx, x, y)
) AS p
CROSS JOIN LATERAL (
    SELECT id, geom_m, length_m FROM routing_trailedge
    WHERE region = %s AND ST_DWithin(geom_m, p.g, %s)
    ORDER BY geom_m <-> p.g, id LIMIT 1
) AS e
"""


def _nearest_edges(
    region: str, points: list[tuple[float, float]], max_m: float
) -> dict[int, tuple[int, float, float]]:
    """Point index -> (edge id, distance_m to it, metres along it from its start) for the
    nearest edge of the region's graph within `max_m`, in one index-ordered query."""
    if not points:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            NEAREST_EDGE_SQL,
            [
                METRIC_SRID,
                list(range(len(points))),
                [x for x, _ in points],
                [y for _, y in points],
                region,
                max_m,
            ],
        )
        return {idx: (edge, distance, along) for idx, edge, distance, along in cursor.fetchall()}


def compute_region(region: str) -> Summary:
    conf = settings()
    box = Polygon.from_bbox(get_region(region).bbox)
    box.srid = 4326
    graph = region_graph(region)[0].graph
    summary = Summary(region)

    # Trailheads join at their nearest node: they sit at a trail's end or on a road.
    index = access.NodeIndex(graph.coords, conf["trailhead_max_m"])
    trailheads = Landmark.objects.filter(
        kind=Landmark.Kind.TRAILHEAD, geom__intersects=box
    ).order_by("source_id")
    sources: dict[int, str] = {}
    for trailhead, x, y in _metric_points(trailheads):
        summary.trailheads += 1
        hit = index.nearest(x, y, conf["trailhead_max_m"])
        if hit is None:
            continue
        summary.trailheads_joined += 1
        name = (trailhead.name or "").strip() or "an unnamed trailhead"
        # Two trailheads on one node: the first by source id keeps it.
        sources.setdefault(hit[0], name)
    reach = access.from_trailheads(graph, sources)

    # Campsites join at their nearest point on an edge, which is usually between nodes.
    facts = {
        row.campsite_id: row for row in CampsiteFacts.objects.filter(campsite__geom__intersects=box)
    }
    points = _metric_points(Campsite.objects.filter(pk__in=list(facts)).order_by("id"))
    nearest = _nearest_edges(region, [(x, y) for _, x, y in points], conf["campsite_max_m"])
    samples = dict(
        TrailEdge.objects.filter(id__in={hit[0] for hit in nearest.values()}).values_list(
            "id", "samples"
        )
    )
    updated = []
    for position, (site, _, _) in enumerate(points):
        hit = nearest.get(position)
        if hit is None or hit[0] not in graph.edges:
            result = access.site_access(None, None, conf)
        else:
            edge_id, approach_m, along_m = hit
            edge = graph.edges[edge_id]
            profile = samples.get(edge_id) or []
            up_from_u, _ = _climb_between(profile, 0.0, along_m)
            _, up_from_v = _climb_between(profile, along_m, edge.length_m)
            point_reach = access.reach_along_edge(reach, edge, along_m, up_from_u, up_from_v)
            result = access.site_access(point_reach, approach_m, conf)
        row = facts[site.pk]
        row.access_class = result.access_class
        row.access_reason = result.reason
        row.access_trailhead = result.trailhead
        row.access_distance_m = _round(result.distance_m)
        row.access_gain_m = _round(result.gain_m)
        row.access_time_s = _round(result.time_s)
        updated.append(row)
        summary.by_class[result.access_class] = summary.by_class.get(result.access_class, 0) + 1
    with transaction.atomic():
        CampsiteFacts.objects.bulk_update(updated, ACCESS_FIELDS, batch_size=500)
    summary.campsites = len(updated)
    return summary


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def payload(facts: CampsiteFacts | None) -> dict | None:
    """The API's `access` object; null before `compute_access` has run for the site."""
    if facts is None or not facts.access_class:
        return None
    return {
        "class": facts.access_class,
        "label": access.LABELS.get(facts.access_class, facts.access_class),
        "reason": facts.access_reason,
        "trailhead": facts.access_trailhead or None,
        "distance_m": facts.access_distance_m,
        "gain_m": facts.access_gain_m,
        "time_s": facts.access_time_s,
    }
