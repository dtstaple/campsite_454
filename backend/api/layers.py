"""
Map layers: turning PostGIS rows into a GeoJSON FeatureCollection.

Why there is a cap
------------------
Measured against the real Adirondack data, an uncapped bounding box covering the whole
park serialises to roughly 151 MB -- 135 MB of water alone across 63,407 features, plus
11 MB of trails across 26,005. No browser survives that, so the cap is not a nicety.

Simplification helps but cannot replace the cap: simplifying the full park to a 110 m
tolerance gets water down to 8.8 MB, but costs 6.5 seconds of database time to do it.
Capping first and simplifying only the rows that survive is both faster and smaller.

Why the cap samples rather than truncates
-----------------------------------------
Taking the first N rows in primary-key order returns whatever the table scans first,
which is an ingest-order blob. Measured over a 10x10 grid across the park, primary-key
order filled **14 of 140 occupied cells** -- a dense clump in one corner and empty space
everywhere else, which reads as "there is no water here" rather than "there is more than
we can draw".

Four orderings were measured on the real data:

    ORDER BY id            14/140 cells   the blob
    ORDER BY ST_Area DESC 103/140 cells   but 2000 polygons and ZERO linestrings --
                                          every stream and river disappears, because a
                                          line has no area so they all tie at zero
    ORDER BY random()     107/140 cells   good spread, but reshuffles every request, so
                                          panning back shows different features and
                                          nothing can be cached
    hash of the id        110/140 cells   best spread, preserves the line/polygon mix
                                          (73% lines, matching the population), and is
                                          deterministic

So the ordering is a cheap multiplicative hash of the primary key. It behaves like a
random sample but is stable: the same bounding box always returns the same features, so
the client can cache and a pan back is not a visual reshuffle.

Deliberately not done: rejecting large bounding boxes. With the cap in place a whole-park
request is cheap, and a 400 would be a worse experience than a truncated answer that says
so. The truncation flag carries the same information without failing the request.
"""

import json
from dataclasses import dataclass
from typing import Any

from django.contrib.gis.db.models import GeometryField
from django.contrib.gis.db.models.functions import AsGeoJSON
from django.contrib.gis.geos import Polygon
from django.db.models import Func, IntegerField, Value

from geodata.models import Campsite, Trail, WaterFeature


class SimplifyPreserveTopology(Func):
    """PostGIS ST_SimplifyPreserveTopology; Django ships no wrapper for it.

    The topology-preserving variant rather than plain ST_Simplify: it will not collapse a
    polygon into an invalid shape, which matters because the output goes straight to a map.
    """

    function = "ST_SimplifyPreserveTopology"
    output_field = GeometryField()


class SampleOrder(Func):
    """A deterministic pseudo-random ordering key derived from the primary key.

    Knuth's multiplicative constant against a large prime modulus: cheap to compute per
    row, spreads ingest-ordered keys evenly, and is stable across requests.
    """

    # mod() rather than the % operator: a literal percent in a Func template has to
    # survive both Django's string formatting and psycopg's parameter parsing, and
    # gets misread as a placeholder.
    template = "mod(%(expressions)s * 2654435761, 2147483647)"
    output_field = IntegerField()


# PostGIS defaults to 9 decimal places, which is sub-millimetre and meaningless for a
# hiking map. Six places is about 11 cm and cuts the geometry payload by roughly 15%.
COORDINATE_PRECISION = 6

# A caller may ask for more than the area-derived default, but not without bound.
MAX_LIMIT = 6000

# Used when no bounding box area is available to derive a cap from.
DEFAULT_LIMIT = 2000

# Cap by bounding-box area in square degrees, smallest area first.
#
# The relationship is inverse. Zoomed in, the full set is usually small and a generous
# cap returns all of it, so nothing is lost. Zoomed out, a *smaller* cap is better:
# 1,500 features spread evenly across the park reads as a map where 2,000 in ingest
# order read as a blob, and the smaller payload is faster.
#
#   <= 0.01 sq deg   roughly one valley          6000
#   <= 0.1  sq deg   a cluster of valleys        4000
#   <= 1.0  sq deg   a large sub-region          2500
#   <= 5.0  sq deg   the Adirondacks (3.99)      1500
#   above            multi-region                1000
LIMIT_BY_AREA: tuple[tuple[float, int], ...] = (
    (0.01, 6000),
    (0.1, 4000),
    (1.0, 2500),
    (5.0, 1500),
)
LIMIT_BEYOND = 1000

# Simplification tolerance is in degrees, because that is the unit the geometry is stored
# in. Roughly: 0.0001 is 11 m, 0.001 is 110 m. Above this the shapes stop resembling
# themselves, so a larger request is a mistake rather than an intention.
MAX_SIMPLIFY = 0.05


def limit_for_bbox(bbox: tuple[float, float, float, float]) -> int:
    """The default cap for a bounding box, derived from its area. See LIMIT_BY_AREA."""
    west, south, east, north = bbox
    area = abs(east - west) * abs(north - south)
    for threshold, limit in LIMIT_BY_AREA:
        if area <= threshold:
            return limit
    return LIMIT_BEYOND


@dataclass(frozen=True)
class Layer:
    """One queryable map layer."""

    name: str
    model: Any
    #: Model fields exposed as GeoJSON Feature properties, in the order the frontend sees.
    properties: tuple[str, ...]

    def queryset(self, bounds: Polygon, limit: int, simplify: float | None):
        geometry = SimplifyPreserveTopology("geom", Value(simplify)) if simplify else "geom"
        return (
            self.model.objects.filter(geom__bboverlaps=bounds)
            .annotate(
                geojson=AsGeoJSON(geometry, precision=COORDINATE_PRECISION),
                sample_order=SampleOrder("id"),
            )
            .values("source_id", "geojson", *self.properties)
            .order_by("sample_order")[:limit]
        )


LAYERS: dict[str, Layer] = {
    "campsites": Layer(
        name="campsites",
        model=Campsite,
        properties=("name", "site_type", "reservable", "capacity"),
    ),
    "trails": Layer(
        name="trails",
        model=Trail,
        properties=("name", "trail_type", "length_m"),
    ),
    "water": Layer(
        name="water",
        model=WaterFeature,
        properties=("name", "feature_type", "perennial"),
    ),
}


def envelope(bbox: tuple[float, float, float, float]) -> Polygon:
    """The bbox as a GEOS polygon in EPSG:4326, ready for a `&&` index lookup."""
    bounds = Polygon.from_bbox(bbox)
    bounds.srid = 4326
    return bounds


def collect(
    layer: Layer,
    bbox: tuple[float, float, float, float],
    *,
    limit: int | None = None,
    simplify: float | None = None,
    bounds: Polygon | None = None,
) -> dict:
    """One layer inside `bbox` as a GeoJSON FeatureCollection.

    `limit` defaults to the area-derived cap. `bounds` may be supplied by a caller that
    has already built the envelope, so a multi-layer request builds it once rather than
    once per layer.

    `bbox` and `metadata` are foreign members, which RFC 7946 permits. MapLibre ignores
    what it does not recognise, so the document stays directly consumable.
    """
    if limit is None:
        limit = limit_for_bbox(bbox)
    if bounds is None:
        bounds = envelope(bbox)

    rows = list(layer.queryset(bounds, limit, simplify))

    # Only pay for the count when the cap might have bitten. On the full park this is
    # about 130 ms; on a small box the cap is never reached and it costs nothing.
    truncated = len(rows) >= limit
    matched = (
        layer.model.objects.filter(geom__bboverlaps=bounds).count() if truncated else len(rows)
    )

    features = [
        {
            "type": "Feature",
            "id": row["source_id"],
            "geometry": json.loads(row["geojson"]),
            "properties": {key: row[key] for key in layer.properties},
        }
        for row in rows
    ]

    return {
        "type": "FeatureCollection",
        "bbox": list(bbox),
        "features": features,
        "metadata": {
            "layer": layer.name,
            "returned": len(features),
            "matched": matched,
            "truncated": truncated,
            "limit": limit,
            "simplify": simplify,
        },
    }
