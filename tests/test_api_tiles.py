"""
Vector tile endpoint tests (TM05-140): /api/tiles/<layer>/<z>/<x>/<y>.mvt.

Every tile is decoded with a small protobuf reader against the Mapbox Vector Tile 2.1
schema, so "valid MVT" means the bytes really parse into layers, features, attributes
and geometry commands. The reader is below; it avoids a test-only dependency.
"""

import gzip
import math
import struct

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Polygon
from django.test import Client

from api.tiles import CACHE_CONTROL, CONTENT_TYPE, EXTENT, MAX_ZOOM, TILE_LAYERS, tile_sql
from geodata.models import PublicLand, Trail, WaterFeature

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

LON, LAT = -73.952, 44.158  # Marcy Dam


@pytest.fixture
def client():
    return Client()


# --- a minimal MVT reader ---------------------------------------------------------------


def _varint(data: bytes, i: int) -> tuple[int, int]:
    shift = value = 0
    while True:
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7


def _fields(data: bytes):
    """(field number, wire type, value) for each field of one protobuf message."""
    i = 0
    while i < len(data):
        key, i = _varint(data, i)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(data, i)
        elif wire == 2:
            length, i = _varint(data, i)
            value, i = data[i : i + length], i + length
        elif wire == 5:
            value, i = data[i : i + 4], i + 4
        elif wire == 1:
            value, i = data[i : i + 8], i + 8
        else:
            raise AssertionError(f"unexpected wire type {wire}")
        yield number, wire, value


def _packed(data: bytes) -> list[int]:
    values, i = [], 0
    while i < len(data):
        value, i = _varint(data, i)
        values.append(value)
    return values


def _value(data: bytes):
    for number, _, raw in _fields(data):
        if number == 1:
            return raw.decode()
        if number == 2:
            return struct.unpack("<f", raw)[0]
        if number == 3:
            return struct.unpack("<d", raw)[0]
        if number in (4, 5):
            return raw
        if number == 6:
            return (raw >> 1) ^ -(raw & 1)
        if number == 7:
            return bool(raw)
    raise AssertionError("empty Value")


def decode_tile(body: bytes) -> dict[str, dict]:
    """{layer name: {"version", "extent", "features": [{"id", "type", "properties",
    "geometry"}]}}. Geometry stays as the raw command integers."""
    layers = {}
    for number, _, layer_bytes in _fields(body):
        assert number == 3, "a Tile holds only layers (field 3)"
        layer = {"version": 1, "extent": 4096, "keys": [], "values": [], "raw": []}
        for field, _, value in _fields(layer_bytes):
            if field == 15:
                layer["version"] = value
            elif field == 1:
                layer["name"] = value.decode()
            elif field == 2:
                layer["raw"].append(value)
            elif field == 3:
                layer["keys"].append(value.decode())
            elif field == 4:
                layer["values"].append(_value(value))
            elif field == 5:
                layer["extent"] = value
        features = []
        for raw in layer.pop("raw"):
            feature = {"id": None, "type": 0, "tags": [], "geometry": []}
            for field, _, value in _fields(raw):
                if field == 1:
                    feature["id"] = value
                elif field == 2:
                    feature["tags"] = _packed(value)
                elif field == 3:
                    feature["type"] = value
                elif field == 4:
                    feature["geometry"] = _packed(value)
            tags = feature.pop("tags")
            feature["properties"] = {
                layer["keys"][tags[k]]: layer["values"][tags[k + 1]] for k in range(0, len(tags), 2)
            }
            features.append(feature)
        layer["features"] = features
        layers[layer["name"]] = layer
    return layers


def vertex_count(geometry: list[int]) -> int:
    """Vertices in an MVT command stream: MoveTo (1) and LineTo (2) carry 2 ints each."""
    count, i = 0, 0
    while i < len(geometry):
        command, repeat = geometry[i] & 7, geometry[i] >> 3
        i += 1
        if command in (1, 2):
            count += repeat
            i += 2 * repeat
    return count


# --- fixtures and helpers --------------------------------------------------------------


def tile_of(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    rad = math.radians(lat)
    y = int((1 - math.log(math.tan(rad) + 1 / math.cos(rad)) / math.pi) / 2 * n)
    return x, y


def get_tile(client, layer: str, z: int, lon: float = LON, lat: float = LAT, **headers):
    x, y = tile_of(lon, lat, z)
    return client.get(f"/api/tiles/{layer}/{z}/{x}/{y}.mvt", **headers)


def make_trail(source_id="way/1", coords=None, **kwargs):
    coords = coords or [(LON, LAT), (LON + 0.002, LAT + 0.001)]
    return Trail.objects.create(
        source=Trail.Source.OSM,
        source_id=source_id,
        name=kwargs.pop("name", "Van Hoevenberg Trail"),
        geom=MultiLineString(LineString(coords, srid=4326), srid=4326),
        trail_type=kwargs.pop("trail_type", "path"),
        length_m=kwargs.pop("length_m", 1234.5),
    )


def make_water(source_id="nhd/1", *, perennial=True, feature_type="stream", offset=0.0):
    return WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id=source_id,
        name="Marcy Brook",
        geom=LineString((LON + offset, LAT), (LON + offset + 0.002, LAT + 0.002), srid=4326),
        feature_type=feature_type,
        perennial=perennial,
    )


def make_public_land(source_id="padus/1", span=0.01):
    square = Polygon.from_bbox((LON - span / 2, LAT - span / 2, LON + span / 2, LAT + span / 2))
    square.srid = 4326
    return PublicLand.objects.create(
        source=PublicLand.Source.PADUS,
        source_id=source_id,
        name="High Peaks Wilderness",
        geom=MultiPolygon(square, srid=4326),
        manager="State Department of Conservation",
        designation="State Wilderness",
        public_access=PublicLand.Access.OPEN,
        gap_status=PublicLand.GapStatus.PERMANENT_NATURAL,
    )


# --- valid MVT ------------------------------------------------------------------------


def test_trail_tile_is_valid_mvt_with_the_attributes_the_panel_needs(client):
    trail = make_trail()
    response = get_tile(client, "trails", 14)

    assert response.status_code == 200
    assert response["Content-Type"] == CONTENT_TYPE
    layers = decode_tile(response.content)
    assert list(layers) == ["trails"]
    layer = layers["trails"]
    assert layer["version"] == 2
    assert layer["extent"] == EXTENT

    [feature] = layer["features"]
    # MVT ids are integers: the primary key. The string id the panel fetches by rides
    # along as `source_id`, which is where sourceIdOf() reads it.
    assert feature["id"] == trail.pk
    assert feature["type"] == 2  # LINESTRING
    assert feature["properties"] == {
        "source_id": "way/1",
        "name": "Van Hoevenberg Trail",
        "trail_type": "path",
        "length_m": 1234.5,
    }
    # The command stream opens with a MoveTo, then LineTo(s).
    assert feature["geometry"][0] & 7 == 1
    assert vertex_count(feature["geometry"]) >= 2


def test_public_land_tile_carries_polygons(client):
    make_public_land()
    layers = decode_tile(get_tile(client, "public-land", 12).content)
    [feature] = layers["public-land"]["features"]
    assert feature["type"] == 3  # POLYGON
    assert feature["geometry"][-1] & 7 == 7  # each ring ends with ClosePath


def test_geometry_lies_where_it_is_in_tile_coordinates(client):
    """A line drawn from the tile centre towards its north-east stays in that quadrant."""
    z = 14
    x, y = tile_of(LON, LAT, z)
    n = 2**z
    west, east = x / n * 360 - 180, (x + 1) / n * 360 - 180

    def lat_of(row):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))

    north, south = lat_of(y), lat_of(y + 1)
    centre = ((west + east) / 2, (north + south) / 2)
    corner = (west + 0.75 * (east - west), south + 0.75 * (north - south))
    make_trail(coords=[centre, corner])

    [feature] = decode_tile(client.get(f"/api/tiles/trails/{z}/{x}/{y}.mvt").content)["trails"][
        "features"
    ]
    geometry = feature["geometry"]
    start = ((geometry[1] >> 1) ^ -(geometry[1] & 1), (geometry[2] >> 1) ^ -(geometry[2] & 1))
    assert abs(start[0] - EXTENT / 2) <= 2 and abs(start[1] - EXTENT / 2) <= 2
    dx = (geometry[4] >> 1) ^ -(geometry[4] & 1)
    dy = (geometry[5] >> 1) ^ -(geometry[5] & 1)
    # Tile y grows downward, so north-east is +x and -y.
    assert dx > 0 and dy < 0


def test_a_line_crossing_a_tile_edge_is_in_both_tiles(client):
    """The buffer keeps lines continuous across tile edges: no seams."""
    z = 14
    x, y = tile_of(LON, LAT, z)
    edge = (x + 1) / 2**z * 360 - 180  # the tile's east edge
    make_trail(coords=[(edge - 0.001, LAT), (edge + 0.001, LAT)])
    left = decode_tile(client.get(f"/api/tiles/trails/{z}/{x}/{y}.mvt").content)
    right = decode_tile(client.get(f"/api/tiles/trails/{z}/{x + 1}/{y}.mvt").content)
    assert len(left["trails"]["features"]) == 1
    assert len(right["trails"]["features"]) == 1


# --- empty tiles and bad requests ------------------------------------------------------


def test_an_empty_tile_is_a_204_with_cache_headers(client):
    make_trail()
    response = get_tile(client, "trails", 12, lon=-140.0, lat=10.0)
    assert response.status_code == 204
    assert response.content == b""
    assert response["Cache-Control"] == CACHE_CONTROL


def test_below_a_layers_minzoom_the_tile_is_empty(client):
    make_trail()
    assert TILE_LAYERS["trails"].minzoom == 9
    assert get_tile(client, "trails", 8).status_code == 204
    assert get_tile(client, "trails", 9).status_code == 200


def test_an_empty_database_still_answers_204(client):
    for layer in TILE_LAYERS:
        assert get_tile(client, layer, 12).status_code == 204


def test_tiles_are_cacheable(client):
    make_trail()
    response = get_tile(client, "trails", 13)
    assert response["Cache-Control"] == CACHE_CONTROL
    assert "max-age=3600" in response["Cache-Control"]


def test_tiles_are_gzipped_when_the_browser_accepts_it(client):
    for index in range(40):
        make_trail(source_id=f"way/{index}", coords=[(LON, LAT + index * 1e-5), (LON + 0.002, LAT)])
    response = get_tile(client, "trails", 14, HTTP_ACCEPT_ENCODING="gzip")
    assert response["Content-Encoding"] == "gzip"
    assert decode_tile(gzip.decompress(response.content))["trails"]["features"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/tiles/campsites/12/1206/1486.mvt",  # not a tiled layer
        "/api/tiles/nothing/12/1206/1486.mvt",
        f"/api/tiles/trails/{MAX_ZOOM + 1}/0/0.mvt",  # beyond the served zooms
        "/api/tiles/trails/3/8/0.mvt",  # x outside 0..2^z-1
        "/api/tiles/trails/3/0/8.mvt",
    ],
)
def test_unknown_layers_and_impossible_tiles_are_404(client, path):
    assert client.get(path).status_code == 404


# --- attributes, rows and simplification per zoom -------------------------------------


def test_water_attributes_grow_with_zoom(client):
    make_water()
    low = decode_tile(get_tile(client, "water", 11).content)["water"]["features"][0]
    high = decode_tile(get_tile(client, "water", 12).content)["water"]["features"][0]
    assert low["properties"] == {
        "source_id": "nhd/1",
        "name": "Marcy Brook",
        "feature_type": "stream",
    }
    assert high["properties"]["perennial"] is True


def test_public_land_detail_attributes_start_at_zoom_10(client):
    make_public_land(span=0.2)
    low = decode_tile(get_tile(client, "public-land", 9).content)["public-land"]["features"][0]
    high = decode_tile(get_tile(client, "public-land", 10).content)["public-land"]["features"][0]
    assert set(low["properties"]) == {"source_id", "name", "public_access"}
    assert set(high["properties"]) == {
        "source_id",
        "name",
        "public_access",
        "manager",
        "designation",
        "gap_status",
    }


def test_intermittent_streams_wait_for_zoom_11(client):
    make_water("nhd/perennial", perennial=True)
    make_water("nhd/intermittent", perennial=False, offset=0.0005)
    make_water("nhd/unknown", perennial=None, offset=0.001)
    make_water("nhd/lake", perennial=None, feature_type="lake", offset=0.0015)

    def ids(z):
        layer = decode_tile(get_tile(client, "water", z).content)["water"]
        return sorted(f["properties"]["source_id"] for f in layer["features"])

    assert ids(10) == ["nhd/lake", "nhd/perennial"]
    assert ids(11) == ["nhd/intermittent", "nhd/lake", "nhd/perennial", "nhd/unknown"]


def test_low_zoom_tiles_are_simplified(client):
    """A wiggly line keeps its wiggles at full detail and loses them zoomed out."""
    wiggle = [(LON + i * 0.00002, LAT + (0.00005 if i % 2 else 0)) for i in range(200)]
    make_trail(coords=wiggle)
    detail = decode_tile(get_tile(client, "trails", 14).content)["trails"]["features"][0]
    overview = decode_tile(get_tile(client, "trails", 9).content)["trails"]["features"][0]
    assert vertex_count(detail["geometry"]) > 150
    assert vertex_count(overview["geometry"]) < 10


def test_every_layer_is_simplified_only_below_its_full_detail_zoom():
    for layer in TILE_LAYERS.values():
        assert "ST_Simplify" in tile_sql(layer, layer.full_detail_zoom - 1)
        assert "ST_Simplify" not in tile_sql(layer, layer.full_detail_zoom)
