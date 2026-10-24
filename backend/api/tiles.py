"""
Map layers as Mapbox Vector Tiles, straight from PostGIS (TM05-140).

    GET /api/tiles/<layer>/<z>/<x>/<y>.mvt

Trails, water and public land used to be GeoJSON per viewport, capped and sampled
(api/layers.py explains why the GeoJSON path has to be). A tile is a fixed piece of the
world at one zoom, so PostGIS does the clipping, simplifying and encoding in a single
ST_AsMVT query. Nothing has to be capped, and the browser caches every tile it has seen.

Per zoom, a layer chooses:

- **Which rows.** For example, water below zoom 11 leaves out intermittent streams,
  which are sub-pixel there.
- **Which attributes.** Low zooms carry only what the map draws or a click needs.
- **How much simplification.** Roughly one tile pixel (`SIMPLIFY_PX`) up to
  `full_detail_zoom`; from there on, ST_AsMVTGeom's own snap to the 4096 grid is the
  only loss.

Adding a layer means one `TileLayer` entry in `TILE_LAYERS`: a model, a minimum zoom,
and the attributes to send from which zoom. docs/api.md walks through it.

Feature ids: MVT ids must be integers, so each feature's id is the row's primary key.
The `source_id` string the trail panel needs ("way/123") travels as an attribute, which
is where `sourceIdOf()` on the frontend already reads it.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import connection
from django.http import Http404, HttpResponse

from geodata.models import PublicLand, Trail, WaterFeature
from terrain.models import TerrainZone

#: Tile coordinate space (ST_AsMVT's default): 4096 units across a tile.
EXTENT = 4096
#: Geometry this far outside the tile (in tile units) is kept, so lines and polygon
#: edges don't show seams where tiles meet.
BUFFER = 64
#: Tiles above this zoom aren't served: MapLibre overzooms the z14 tile, which at 4096
#: units across already resolves under a metre in the Adirondacks.
MAX_ZOOM = 14
#: Simplification tolerance in tile pixels (256 per tile) below `full_detail_zoom`.
SIMPLIFY_PX = 0.5
#: The web-mercator world's width in metres.
WORLD_M = 40075016.68557849

CONTENT_TYPE = "application/vnd.mapbox-vector-tile"
#: Tiles change only when an ingest runs. An hour in the browser, and a stale tile may
#: be served for a day while it revalidates.
CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"


@dataclass(frozen=True)
class TileLayer:
    """One layer of the tile endpoint. See the module docstring."""

    name: str
    model: type
    #: No tile below this zoom: an empty 204. The map's layer minzoom matches it.
    minzoom: int
    #: (from zoom, attribute names) pairs, ascending. A tile at zoom z carries every
    #: attribute listed at or below z. `source_id` and `name` belong first.
    attributes: tuple[tuple[int, tuple[str, ...]], ...]
    #: (below zoom, SQL condition) pairs: under that zoom only rows matching the
    #: condition are drawn. Conditions are constant SQL on the model's columns.
    thin: tuple[tuple[int, str], ...] = ()
    #: From this zoom up, geometry is not simplified beyond the tile grid.
    full_detail_zoom: int = 13
    #: A constant SQL condition picking this layer's rows, for a model that holds more
    #: than one layer (terrain zones).
    where: str = ""

    def attributes_at(self, z: int) -> list[str]:
        return [name for start, names in self.attributes if z >= start for name in names]

    def conditions_at(self, z: int) -> list[str]:
        thinned = [condition for below, condition in self.thin if z < below]
        return [self.where, *thinned] if self.where else thinned


TILE_LAYERS: dict[str, TileLayer] = {
    "trails": TileLayer(
        name="trails",
        model=Trail,
        minzoom=9,
        # Everything the popup and the trail panel read, at every zoom: a trail is
        # clickable wherever it is drawn. The attributes are short.
        attributes=((0, ("source_id", "name", "trail_type", "length_m")),),
    ),
    "water": TileLayer(
        name="water",
        model=WaterFeature,
        minzoom=9,
        attributes=(
            (0, ("source_id", "name", "feature_type")),
            (12, ("perennial",)),
        ),
        # At zooms 9-10 an intermittent stream is a sub-pixel scribble, and there are tens
        # of thousands. Lakes, wetlands and perennial streams carry the picture.
        thin=((11, "NOT (feature_type = 'stream' AND perennial IS NOT TRUE)"),),
    ),
    "public-land": TileLayer(
        name="public-land",
        model=PublicLand,
        minzoom=0,
        attributes=(
            (0, ("source_id", "name", "public_access")),
            (10, ("manager", "designation", "gap_status")),
        ),
        full_detail_zoom=12,
    ),
    # TM05-141: terrain zones, merged and simplified by `make terrain`.
    "pooling-risk": TileLayer(
        name="pooling-risk",
        model=TerrainZone,
        minzoom=8,
        attributes=((0, ("zone_class",)),),
        where="layer = 'pooling-risk' AND tile = ''",
        full_detail_zoom=12,
    ),
    "exposure": TileLayer(
        name="exposure",
        model=TerrainZone,
        minzoom=8,
        attributes=((0, ("zone_class",)),),
        where="layer = 'exposure' AND tile = ''",
        full_detail_zoom=12,
    ),
}


def tolerance_m(z: int) -> float:
    """Simplification tolerance in web-mercator metres for a tile at zoom `z`."""
    return WORLD_M / (256 * 2**z) * SIMPLIFY_PX


def tile_sql(layer: TileLayer, z: int) -> str:
    """The ST_AsMVT query for one tile, with %(z)s, %(x)s and %(y)s left as parameters.

    Rows are found with the 4326 geometry index against the tile envelope reprojected
    to 4326. Each is cut to that envelope, transformed to web mercator, simplified
    (below full detail) and encoded into tile coordinates.
    """
    table = layer.model._meta.db_table
    columns = "".join(f', t."{name}"' for name in layer.attributes_at(z))
    # Clipped to the (buffered) tile in 4326 first, so a PAD-US parcel spanning the
    # country is cut to the tile before it is reprojected, not after.
    geometry = "ST_Transform(ST_ClipByBox2D(t.geom, bounds.geo::box2d), 3857)"
    if z < layer.full_detail_zoom:
        geometry = f"ST_Simplify({geometry}, {tolerance_m(z)!r}, true)"
    where = "".join(f" AND ({condition})" for condition in layer.conditions_at(z))
    return f"""
        WITH bounds AS (
            SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS merc,
                   ST_Transform(
                       ST_TileEnvelope(%(z)s, %(x)s, %(y)s, margin => {BUFFER / EXTENT}), 4326
                   ) AS geo
        ),
        features AS (
            SELECT t.id AS fid{columns},
                   ST_AsMVTGeom({geometry}, bounds.merc, {EXTENT}, {BUFFER}, true) AS mvtgeom
            FROM "{table}" t, bounds
            WHERE t.geom && bounds.geo{where}
        )
        SELECT ST_AsMVT(features.*, %(name)s, {EXTENT}, 'mvtgeom', 'fid')
        FROM features
        WHERE mvtgeom IS NOT NULL
    """


def render_tile(layer: TileLayer, z: int, x: int, y: int) -> bytes:
    """One encoded tile; b"" when nothing falls in it (or below the layer's minzoom)."""
    if z < layer.minzoom:
        return b""
    with connection.cursor() as cursor:
        cursor.execute(tile_sql(layer, z), {"z": z, "x": x, "y": y, "name": layer.name})
        row = cursor.fetchone()
    return bytes(row[0]) if row and row[0] else b""


def tile_view(request, layer: str, z: int, x: int, y: int):
    """GET /api/tiles/<layer>/<z>/<x>/<y>.mvt -- one vector tile, or 204 when empty.

    Public data, so no authentication and a plain Django view (no DRF content
    negotiation for a binary body). GZipMiddleware compresses it on the way out;
    browsers undo that before MapLibre reads it.
    """
    tile_layer = TILE_LAYERS.get(layer)
    if tile_layer is None:
        raise Http404(f"Unknown tile layer {layer!r}. Available: {', '.join(TILE_LAYERS)}")
    if z > MAX_ZOOM or x >= 2**z or y >= 2**z:
        raise Http404(f"No tile {z}/{x}/{y}: zoom runs 0-{MAX_ZOOM}, x and y below 2^zoom")

    body = render_tile(tile_layer, z, x, y)
    response = HttpResponse(body, content_type=CONTENT_TYPE, status=200 if body else 204)
    response["Cache-Control"] = CACHE_CONTROL
    return response
