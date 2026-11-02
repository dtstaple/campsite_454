"""
Terrain along a route (TM05-152): where a trail or planned route crosses the terrain
pipeline's zones, by distance along it, with totals for the trail panel.

    "1.2 mi exposed ridge", "0.4 mi wet ground"

The zones are the merged `exposure` and `pooling-risk` polygons `make terrain` stores
(TerrainZone, tile ''), the same ones the map draws. Nothing is computed from rasters here.

Distances are measured along the stitched line in EPSG:5070, the line every other
"distance along" in the route detail uses (profile.distance_m, distance_along_m). The line
is cut into its segments first, so a loop or an out-and-back that passes the same ground
twice counts it twice, at the right miles, rather than at its first pass only.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.gis.geos import LineString
from django.db import connection

from terrain.models import TerrainZone
from terrain.payload import NOTE


@dataclass(frozen=True)
class Kind:
    layer: str
    zone_class: str
    #: The summary line's words: "1.2 mi exposed ridge".
    label: str
    #: The legend's one line, as the map's zone overlays say it (frontend terrain/zones.ts).
    legend: str


KINDS: tuple[Kind, ...] = (
    Kind(
        "exposure",
        "high",
        "exposed ridge",
        "Ground that stands above its surroundings, open to wind",
    ),
    Kind(
        "pooling-risk",
        "high",
        "wet ground",
        "Low ground that water drains into",
    ),
)

#: Zone pieces closer than this along the route are one stretch. Zones are merged per tile,
#: not across tiles (docs/terrain-analysis.md), so one ridge can arrive as abutting pieces.
JOIN_GAP_M = 1.0

# Each segment of the line, with the distance along the line at which it starts, crossed
# with the zones it touches. `&&` uses terrainzone_geom_m_gist. A piece's two ends are
# located on its own segment, which is a straight line, so the result is exact.
STRETCHES_SQL = """
WITH line AS (SELECT %s::geometry AS g),
segs AS (
    SELECT d.path[1] AS i, d.geom AS seg, ST_Length(d.geom) AS seg_m
    FROM line, ST_DumpSegments(line.g) AS d
),
placed AS (
    SELECT seg, seg_m,
           COALESCE(SUM(seg_m) OVER (ORDER BY i ROWS BETWEEN UNBOUNDED PRECEDING
                                                     AND 1 PRECEDING), 0) AS start_m
    FROM segs
    WHERE seg_m > 0
),
pieces AS (
    SELECT z.layer, z.zone_class, p.seg, p.seg_m, p.start_m,
           (ST_Dump(ST_Intersection(p.seg, z.geom_m))).geom AS piece
    FROM placed p
    JOIN terrain_terrainzone z ON z.geom_m && p.seg AND ST_Intersects(z.geom_m, p.seg)
    WHERE z.tile = '' AND z.layer = ANY(%s)
)
SELECT layer, zone_class,
       start_m + ST_LineLocatePoint(seg, ST_StartPoint(piece)) * seg_m,
       start_m + ST_LineLocatePoint(seg, ST_EndPoint(piece)) * seg_m
FROM pieces
WHERE ST_GeometryType(piece) = 'ST_LineString'
"""


def merge(intervals: list[tuple[float, float]], gap_m: float = JOIN_GAP_M) -> list[list[float]]:
    """Overlapping or touching (within `gap_m`) intervals as one, in order along the route.
    Each interval may come in either direction."""
    ordered = sorted((min(a, b), max(a, b)) for a, b in intervals)
    merged: list[list[float]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1] + gap_m:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def summarise(pieces: list[tuple[str, str, float, float]], length_m: float) -> dict:
    """The payload from raw (layer, class, from_m, to_m) pieces: merged stretches in route
    order, and one total per kind (zero included, so "none" is an answer, not a gap)."""
    stretches = []
    totals = []
    for kind in KINDS:
        spans = merge(
            [(a, b) for layer, cls, a, b in pieces if (layer, cls) == (kind.layer, kind.zone_class)]
        )
        spans = [(max(0.0, a), min(length_m, b)) for a, b in spans]
        spans = [(a, b) for a, b in spans if b > a]
        total_m = sum(b - a for a, b in spans)
        for a, b in spans:
            stretches.append(
                {
                    "layer": kind.layer,
                    "zone_class": kind.zone_class,
                    "label": kind.label,
                    "start_m": round(a, 1),
                    "end_m": round(b, 1),
                    "length_m": round(b - a, 1),
                }
            )
        totals.append(
            {
                "layer": kind.layer,
                "zone_class": kind.zone_class,
                "label": kind.label,
                "legend": kind.legend,
                "length_m": round(total_m, 1),
                "stretches": len(spans),
                "share_pct": round(100 * total_m / length_m, 1) if length_m > 0 else 0.0,
            }
        )
    stretches.sort(key=lambda s: (s["start_m"], s["layer"]))
    return {"stretches": stretches, "totals": totals}


def route_terrain(line_m: LineString) -> dict:
    """The route detail's `terrain_along` block for a stitched line in EPSG:5070."""
    layers = [kind.layer for kind in KINDS]
    if not TerrainZone.objects.filter(tile="", layer__in=layers).exists():
        return {
            "status": "unavailable",
            "reason": "Terrain zones haven't been computed for this area yet.",
            "stretches": [],
            "totals": [],
            "note": NOTE,
        }
    with connection.cursor() as cursor:
        cursor.execute(STRETCHES_SQL, [line_m.ewkt, layers])
        pieces = cursor.fetchall()
    return {"status": "ok", "reason": None, **summarise(pieces, line_m.length), "note": NOTE}
