"""
Map layers: turning PostGIS rows into a GeoJSON FeatureCollection.

Why there is a cap
------------------
Measured against the real Adirondack data, an uncapped bounding box covering the whole
park serialises to roughly 151 MB -- 135 MB of water alone across 63,407 features, plus
11 MB of trails across 26,005. No browser survives that, so the cap is not a nicety.

Simplification helps but cannot replace the cap: simplifying the full park to a 110 m
tolerance gets water down to 8.8 MB, but costs 6.5 seconds of database time to do it.
Capping first and simplifying only the rows that survive is both faster and smaller --
2,000 water features at that tolerance is 230 kB in 193 ms.

So the strategy is: filter by bbox on the GiST index, cap, optionally simplify, and tell
the client honestly when the cap bit. The client decides what to do about it -- usually
prompting the user to zoom in, which it can only do if we say `truncated`.

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
from django.db.models import Func, Value

from geodata.models import Campsite, Trail, WaterFeature


class SimplifyPreserveTopology(Func):
    """PostGIS ST_SimplifyPreserveTopology; Django ships no wrapper for it.

    The topology-preserving variant rather than plain ST_Simplify: it will not collapse a
    polygon into an invalid shape, which matters because the output goes straight to a map.
    """

    function = "ST_SimplifyPreserveTopology"
    output_field = GeometryField()


# Chosen from the measurements above: 2,000 water features simplified is a 230 kB payload,
# which is a reasonable ceiling for a map request.
DEFAULT_LIMIT = 2000

# A caller may ask for more, but not without bound.
MAX_LIMIT = 5000

# Simplification tolerance is in degrees, because that is the unit the geometry is stored
# in. Roughly: 0.0001 is 11 m, 0.001 is 110 m. Above this the shapes stop resembling
# themselves, so a larger request is a mistake rather than an intention.
MAX_SIMPLIFY = 0.05


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
            .annotate(geojson=AsGeoJSON(geometry))
            .values("source_id", "geojson", *self.properties)
            .order_by("id")[:limit]
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
    limit: int = DEFAULT_LIMIT,
    simplify: float | None = None,
) -> dict:
    """One layer inside `bbox` as a GeoJSON FeatureCollection.

    `bbox` and `metadata` are foreign members, which RFC 7946 permits. MapLibre ignores
    what it does not recognise, so the document stays directly consumable.
    """
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
