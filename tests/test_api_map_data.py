"""
Map data API tests.

The GeoJSON assertions validate against RFC 7946 structurally *and* round-trip every
geometry back through GEOS. "Has a features key" would pass on a document MapLibre cannot
render; parsing the geometry proves it is real.
"""

import json

import pytest
from django.contrib.gis.geos import GEOSGeometry, LineString, MultiLineString, Point, Polygon
from django.test import Client

from api.bbox import InvalidBbox, parse_bbox
from api.layers import LIMIT_BEYOND, LIMIT_BY_AREA, MAX_LIMIT, limit_for_bbox
from geodata.models import Campsite, Trail, WaterFeature

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

# The area every fixture row sits inside.
INSIDE = "-74.20,44.00,-73.90,44.20"
# A box in the Pacific, guaranteed to match nothing we create.
ELSEWHERE = "-140.00,10.00,-139.90,10.10"

GEOJSON_GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}


@pytest.fixture
def client():
    return Client()


def assert_valid_geojson(document: dict):
    """Validate a FeatureCollection against RFC 7946, geometry included."""
    assert document["type"] == "FeatureCollection"
    assert isinstance(document["features"], list)

    # bbox is a foreign-member-free standard: 4 numbers, west,south,east,north.
    assert len(document["bbox"]) == 4
    assert all(isinstance(value, int | float) for value in document["bbox"])

    for feature in document["features"]:
        assert feature["type"] == "Feature"
        assert isinstance(feature["properties"], dict)

        geometry = feature["geometry"]
        assert geometry["type"] in GEOJSON_GEOMETRY_TYPES, geometry["type"]
        assert "coordinates" in geometry

        # The real check: GEOS must be able to parse it back.
        parsed = GEOSGeometry(json.dumps(geometry))
        assert not parsed.empty


def make_campsite(source_id="c1", lon=-74.05, lat=44.10, **kwargs):
    return Campsite.objects.create(
        source=Campsite.Source.RIDB,
        source_id=source_id,
        name=kwargs.pop("name", "Marcy Dam"),
        geom=Point(lon, lat, srid=4326),
        site_type=kwargs.pop("site_type", Campsite.SiteType.LEAN_TO),
        **kwargs,
    )


def make_trail(source_id="t1", lon=-74.05, lat=44.10):
    line = LineString((lon, lat), (lon + 0.01, lat + 0.01), srid=4326)
    return Trail.objects.create(
        source=Trail.Source.OSM,
        source_id=source_id,
        name="Van Hoevenberg",
        geom=MultiLineString(line, srid=4326),
        trail_type="path",
        length_m=1234.5,
    )


def make_water(source_id="w1", lon=-74.05, lat=44.10):
    return WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id=source_id,
        name="Marcy Brook",
        geom=LineString((lon, lat), (lon + 0.01, lat + 0.01), srid=4326),
        feature_type=WaterFeature.FeatureType.STREAM,
        perennial=True,
    )


# --- shape ------------------------------------------------------------------------------


@pytest.mark.parametrize("layer", ["campsites", "trails", "water"])
def test_a_valid_bbox_returns_wellformed_geojson(client, layer):
    make_campsite()
    make_trail()
    make_water()

    response = client.get(f"/api/{layer}/?bbox={INSIDE}")

    assert response.status_code == 200
    document = response.json()
    assert_valid_geojson(document)
    assert len(document["features"]) == 1
    assert document["metadata"]["layer"] == layer


def test_campsite_properties_are_the_ones_the_frontend_needs(client):
    make_campsite(reservable=True, capacity=8)

    feature = client.get(f"/api/campsites/?bbox={INSIDE}").json()["features"][0]

    assert feature["id"] == "c1"
    assert feature["geometry"]["type"] == "Point"
    assert feature["properties"] == {
        "name": "Marcy Dam",
        "site_type": "lean_to",
        "reservable": True,
        "capacity": 8,
    }


def test_trail_properties_include_length(client):
    make_trail()

    feature = client.get(f"/api/trails/?bbox={INSIDE}").json()["features"][0]

    assert feature["properties"]["trail_type"] == "path"
    assert feature["properties"]["length_m"] == pytest.approx(1234.5)
    assert feature["geometry"]["type"] == "MultiLineString"


def test_water_properties_expose_the_perennial_tristate(client):
    make_water(source_id="w-true")
    WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id="w-unknown",
        geom=Point(-74.06, 44.11, srid=4326),
        feature_type=WaterFeature.FeatureType.LAKE,
        perennial=None,
    )

    features = client.get(f"/api/water/?bbox={INSIDE}").json()["features"]
    perennial = {f["id"]: f["properties"]["perennial"] for f in features}

    assert perennial["w-true"] is True
    assert perennial["w-unknown"] is None, "unknown must stay null, not become false"


# --- emptiness ----------------------------------------------------------------------------


@pytest.mark.parametrize("layer", ["campsites", "trails", "water"])
def test_an_empty_area_is_200_with_an_empty_collection(client, layer):
    make_campsite()
    make_trail()
    make_water()

    response = client.get(f"/api/{layer}/?bbox={ELSEWHERE}")

    assert response.status_code == 200, "an empty area is not an error"
    document = response.json()
    assert_valid_geojson(document)
    assert document["features"] == []
    assert document["metadata"]["matched"] == 0
    assert document["metadata"]["truncated"] is False


def test_an_empty_database_is_also_200(client):
    response = client.get(f"/api/water/?bbox={INSIDE}")

    assert response.status_code == 200
    assert response.json()["features"] == []


# --- spatial filtering ---------------------------------------------------------------------


def test_features_outside_the_bbox_are_excluded(client):
    make_campsite(source_id="inside", lon=-74.05, lat=44.10)
    make_campsite(source_id="outside", lon=-71.00, lat=43.00)

    features = client.get(f"/api/campsites/?bbox={INSIDE}").json()["features"]

    assert [f["id"] for f in features] == ["inside"]


def test_a_feature_straddling_the_edge_is_included(client):
    """bboverlaps is an intersection test, so a trail crossing the edge still counts."""
    crossing = LineString((-73.95, 44.10), (-73.80, 44.10), srid=4326)
    Trail.objects.create(
        source=Trail.Source.OSM,
        source_id="crossing",
        geom=MultiLineString(crossing, srid=4326),
        trail_type="path",
    )

    features = client.get(f"/api/trails/?bbox={INSIDE}").json()["features"]

    assert [f["id"] for f in features] == ["crossing"]


# --- bbox validation -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bbox,expected",
    [
        pytest.param("not-a-bbox", "exactly 4", id="not-four-values"),
        pytest.param("-74,44,-73", "exactly 4", id="three-values"),
        pytest.param("-74,44,-73,45,46", "exactly 4", id="five-values"),
        pytest.param("a,b,c,d", "must all be numbers", id="non-numeric"),
        pytest.param("-73,44,-75,45", "west", id="inverted-longitude"),
        pytest.param("-75,45,-73,44", "south", id="inverted-latitude"),
        pytest.param("-75,44,-75,45", "west", id="zero-width"),
        pytest.param("-200,44,-73,45", "outside -180..180", id="longitude-out-of-range"),
        pytest.param("-75,44,-73,200", "outside -90..90", id="latitude-out-of-range"),
    ],
)
def test_a_bad_bbox_is_400_with_a_specific_reason(client, bbox, expected):
    response = client.get(f"/api/water/?bbox={bbox}")

    assert response.status_code == 400
    assert expected in response.json()["error"]


def test_a_missing_bbox_is_400_and_says_the_format(client):
    response = client.get("/api/water/")

    assert response.status_code == 400
    error = response.json()["error"]
    assert "required" in error
    assert "west,south,east,north" in error


@pytest.mark.unit
@pytest.mark.parametrize("raw", [None, "", "   "])
def test_parse_bbox_rejects_nothing(raw):
    with pytest.raises(InvalidBbox, match="required"):
        parse_bbox(raw)


@pytest.mark.unit
def test_parse_bbox_accepts_whitespace_around_values():
    assert parse_bbox(" -75.4 , 43.0 , -73.3 , 44.9 ") == (-75.4, 43.0, -73.3, 44.9)


# --- cap and truncation -------------------------------------------------------------------------


def test_the_cap_truncates_and_says_so(client):
    for index in range(12):
        make_campsite(source_id=f"c{index}", lon=-74.05 + index * 0.001, lat=44.10)

    document = client.get(f"/api/campsites/?bbox={INSIDE}&limit=5").json()

    assert len(document["features"]) == 5
    assert document["metadata"] == {
        "layer": "campsites",
        "returned": 5,
        "matched": 12,
        "truncated": True,
        "limit": 5,
        "simplify": None,
    }


def test_no_truncation_flag_when_everything_fits(client):
    make_campsite()

    metadata = client.get(f"/api/campsites/?bbox={INSIDE}&limit=5").json()["metadata"]

    assert metadata["truncated"] is False
    assert metadata["returned"] == metadata["matched"] == 1


def test_the_limit_is_capped_at_the_maximum(client):
    make_campsite()

    metadata = client.get(f"/api/campsites/?bbox={INSIDE}&limit=999999").json()["metadata"]

    assert metadata["limit"] == MAX_LIMIT


def test_the_default_limit_is_derived_from_the_bbox_area(client):
    """No explicit limit means the cap scales inversely with how much ground is asked
    for: generous zoomed in, tighter zoomed out. See LIMIT_BY_AREA."""
    make_campsite()

    # INSIDE is 0.3 x 0.2 = 0.06 sq deg, which falls in the <= 0.1 band.
    metadata = client.get(f"/api/campsites/?bbox={INSIDE}").json()["metadata"]

    assert metadata["limit"] == 4000


@pytest.mark.parametrize(
    "value,expected",
    [("0", "at least 1"), ("-3", "at least 1"), ("abc", "whole number")],
)
def test_a_bad_limit_is_400(client, value, expected):
    response = client.get(f"/api/campsites/?bbox={INSIDE}&limit={value}")

    assert response.status_code == 400
    assert expected in response.json()["error"]


# --- simplification ----------------------------------------------------------------------------


def test_simplify_reduces_the_geometry_but_keeps_it_valid(client):
    dense = LineString(
        [(-74.05 + i * 0.0001, 44.10 + (i % 2) * 0.00001) for i in range(200)], srid=4326
    )
    WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id="dense",
        geom=dense,
        feature_type=WaterFeature.FeatureType.STREAM,
    )

    detailed = client.get(f"/api/water/?bbox={INSIDE}").json()
    simplified = client.get(f"/api/water/?bbox={INSIDE}&simplify=0.001").json()

    assert_valid_geojson(simplified)
    detailed_points = len(detailed["features"][0]["geometry"]["coordinates"])
    simplified_points = len(simplified["features"][0]["geometry"]["coordinates"])
    assert simplified_points < detailed_points
    assert simplified["metadata"]["simplify"] == 0.001


def test_simplify_is_reported_as_null_when_not_requested(client):
    make_water()

    assert client.get(f"/api/water/?bbox={INSIDE}").json()["metadata"]["simplify"] is None


@pytest.mark.parametrize(
    "value,expected",
    [("abc", "must be a number"), ("-1", "cannot be negative"), ("10", "would not resemble")],
)
def test_a_bad_simplify_is_400(client, value, expected):
    response = client.get(f"/api/water/?bbox={INSIDE}&simplify={value}")

    assert response.status_code == 400
    assert expected in response.json()["error"]


# --- combined endpoint ---------------------------------------------------------------------------


def test_map_data_returns_every_layer_separately(client):
    make_campsite()
    make_trail()
    make_water()

    document = client.get(f"/api/map-data/?bbox={INSIDE}").json()

    assert set(document["layers"]) == {"campsites", "trails", "water"}
    for collection in document["layers"].values():
        assert_valid_geojson(collection)
        assert len(collection["features"]) == 1
    assert document["metadata"]["returned"] == 3
    assert document["metadata"]["truncated"] is False


def test_map_data_reports_truncation_if_any_layer_truncates(client):
    for index in range(4):
        make_campsite(source_id=f"c{index}", lon=-74.05 + index * 0.001, lat=44.10)
    make_trail()

    document = client.get(f"/api/map-data/?bbox={INSIDE}&limit=2").json()

    assert document["layers"]["campsites"]["metadata"]["truncated"] is True
    assert document["layers"]["trails"]["metadata"]["truncated"] is False
    assert document["metadata"]["truncated"] is True, "the summary must surface it"


def test_map_data_validates_the_bbox_too(client):
    response = client.get("/api/map-data/?bbox=-73,44,-75,45")

    assert response.status_code == 400
    assert "west" in response.json()["error"]


# --- polygons survive the round trip ---------------------------------------------


def test_polygon_water_features_serialize_correctly(client):
    ring = Polygon(
        ((-74.05, 44.10), (-74.03, 44.10), (-74.03, 44.12), (-74.05, 44.12), (-74.05, 44.10)),
        srid=4326,
    )
    WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id="lake",
        name="Lake Colden",
        geom=ring,
        feature_type=WaterFeature.FeatureType.LAKE,
    )

    document = client.get(f"/api/water/?bbox={INSIDE}").json()

    assert_valid_geojson(document)
    geometry = document["features"][0]["geometry"]
    assert geometry["type"] == "Polygon"
    assert GEOSGeometry(json.dumps(geometry)).valid


# --- area-derived caps --------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "bbox,expected",
    [
        pytest.param((-74.05, 44.10, -74.00, 44.15), 6000, id="valley-0.0025sqdeg"),
        pytest.param((-74.20, 44.00, -73.90, 44.20), 4000, id="medium-0.06sqdeg"),
        pytest.param((-74.60, 43.60, -73.90, 44.30), 2500, id="sub-region-0.49sqdeg"),
        pytest.param((-75.40, 43.00, -73.30, 44.90), 1500, id="adirondacks-3.99sqdeg"),
        pytest.param((-80.00, 40.00, -70.00, 46.00), LIMIT_BEYOND, id="multi-region"),
    ],
)
def test_the_cap_scales_inversely_with_area(bbox, expected):
    assert limit_for_bbox(bbox) == expected


@pytest.mark.unit
def test_the_cap_bands_are_ordered_and_decreasing():
    """A larger area must never earn a larger cap."""
    areas = [area for area, _ in LIMIT_BY_AREA]
    caps = [cap for _, cap in LIMIT_BY_AREA]

    assert areas == sorted(areas)
    assert caps == sorted(caps, reverse=True)
    assert caps[-1] > LIMIT_BEYOND


def test_an_explicit_limit_still_overrides_the_area_default(client):
    make_campsite()

    metadata = client.get(f"/api/campsites/?bbox={INSIDE}&limit=7").json()["metadata"]

    assert metadata["limit"] == 7


# --- the sample is deterministic and spatially spread ---------------------------------


def test_the_same_bbox_returns_the_same_sample_twice(client):
    """Deterministic ordering is what makes client caching and stable panning possible.

    ORDER BY random() would pass the spread test but fail this one.
    """
    for index in range(30):
        make_campsite(source_id=f"c{index}", lon=-74.05 + index * 0.002, lat=44.10)

    first = client.get(f"/api/campsites/?bbox={INSIDE}&limit=10").json()
    second = client.get(f"/api/campsites/?bbox={INSIDE}&limit=10").json()

    assert [f["id"] for f in first["features"]] == [f["id"] for f in second["features"]]


def test_the_sample_is_not_simply_the_first_rows_inserted(client):
    """Insertion order is the blob this ordering exists to avoid."""
    for index in range(40):
        make_campsite(source_id=f"c{index:02d}", lon=-74.05 + index * 0.002, lat=44.10)

    returned = {
        f["id"] for f in client.get(f"/api/campsites/?bbox={INSIDE}&limit=10").json()["features"]
    }
    first_ten_inserted = {f"c{index:02d}" for index in range(10)}

    assert returned != first_ten_inserted


# --- payload size -----------------------------------------------------------------------


def test_coordinates_are_not_shipped_at_millimetre_precision(client):
    make_water()

    geometry = client.get(f"/api/water/?bbox={INSIDE}").json()["features"][0]["geometry"]

    for longitude, latitude in geometry["coordinates"]:
        for value in (longitude, latitude):
            decimals = len(str(value).split(".")[1]) if "." in str(value) else 0
            assert decimals <= 6, f"{value} carries more precision than a map can use"


def test_responses_are_gzipped_when_the_client_accepts_it(client):
    make_water()

    response = client.get(f"/api/water/?bbox={INSIDE}", headers={"accept-encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip"


# --- the layers parameter ---------------------------------------------------------------


def test_map_data_returns_only_the_requested_layers(client):
    make_campsite()
    make_trail()
    make_water()

    document = client.get(f"/api/map-data/?bbox={INSIDE}&layers=campsites").json()

    assert set(document["layers"]) == {"campsites"}
    assert document["metadata"]["layers"] == ["campsites"]


def test_map_data_accepts_several_layers(client):
    make_campsite()
    make_trail()
    make_water()

    document = client.get(f"/api/map-data/?bbox={INSIDE}&layers=trails,water").json()

    assert set(document["layers"]) == {"trails", "water"}


def test_map_data_defaults_to_every_layer(client):
    make_campsite()

    document = client.get(f"/api/map-data/?bbox={INSIDE}").json()

    assert set(document["layers"]) == {"campsites", "trails", "water"}


def test_an_unknown_layer_name_is_400_and_lists_the_valid_ones(client):
    response = client.get(f"/api/map-data/?bbox={INSIDE}&layers=elevation")

    assert response.status_code == 400
    error = response.json()["error"]
    assert "elevation" in error
    assert "campsites" in error


def test_skipping_a_layer_actually_shrinks_the_response(client):
    """The whole point: not querying a layer must cost less than querying it."""
    for index in range(50):
        make_water(source_id=f"w{index}", lon=-74.05 + index * 0.001, lat=44.10)
    make_campsite()

    everything = client.get(f"/api/map-data/?bbox={INSIDE}").content
    just_campsites = client.get(f"/api/map-data/?bbox={INSIDE}&layers=campsites").content

    assert len(just_campsites) < len(everything) / 2
