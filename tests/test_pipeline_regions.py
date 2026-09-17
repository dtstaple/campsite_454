"""
Region config and AreaOfInterest tests.

No database needed -- regions are configuration, so these are pure unit tests.
"""

import pytest

from pipeline.aoi import AreaOfInterest, InvalidAreaOfInterest
from pipeline.regions import (
    RegionConfigError,
    UnknownRegionError,
    get_region,
    list_regions,
    load_regions,
)

pytestmark = pytest.mark.unit

NORTHEAST = ["adirondacks", "green-mountains-vt", "maine", "white-mountains-nh"]


def test_shipped_config_defines_the_northeast_regions():
    assert list_regions() == NORTHEAST


def test_regions_load_as_area_of_interest_objects():
    adk = get_region("adirondacks")

    assert isinstance(adk, AreaOfInterest)
    assert adk.label == "Adirondack Park"
    assert adk.states == ("NY",)
    assert adk.notes  # every shipped region documents itself


@pytest.mark.parametrize("name", NORTHEAST)
def test_every_shipped_bbox_is_in_the_northeast_us(name):
    """Guards against a sign flip or a transposed bbox slipping into the config."""
    aoi = get_region(name)

    assert -76 < aoi.min_lon < -66, f"{name} longitude looks wrong: {aoi.bbox}"
    assert 42 < aoi.min_lat < 48, f"{name} latitude looks wrong: {aoi.bbox}"
    assert aoi.min_lon < aoi.max_lon
    assert aoi.min_lat < aoi.max_lat


def test_unknown_region_names_what_is_available():
    with pytest.raises(UnknownRegionError) as err:
        get_region("west-coast")

    message = str(err.value)
    assert "west-coast" in message
    # The error has to be actionable, not just a KeyError.
    assert "adirondacks" in message


def test_as_polygon_is_srid_4326_and_covers_the_bbox():
    aoi = get_region("adirondacks")
    poly = aoi.as_polygon()

    assert poly.srid == AreaOfInterest.SRID == 4326
    assert poly.extent == pytest.approx(aoi.bbox)


def test_overpass_bbox_swaps_to_lat_lon_order():
    aoi = AreaOfInterest(name="x", label="X", bbox=(-75.0, 43.0, -73.0, 44.0))

    assert aoi.as_overpass_bbox() == "43.0,-75.0,44.0,-73.0"


def test_area_of_interest_is_immutable():
    aoi = get_region("maine")

    with pytest.raises(Exception):  # noqa: B017 - dataclasses raises FrozenInstanceError
        aoi.name = "somewhere-else"


@pytest.mark.parametrize(
    "bbox,expected",
    [
        pytest.param((-73.0, 43.0, -75.0, 44.0), "min_lon", id="inverted-lon"),
        pytest.param((-75.0, 44.0, -73.0, 43.0), "min_lat", id="inverted-lat"),
        pytest.param((-500.0, 43.0, -73.0, 44.0), "longitude", id="lon-out-of-range"),
        pytest.param((-75.0, 100.0, -73.0, 120.0), "latitude", id="lat-out-of-range"),
        pytest.param((-75.0, 43.0, -73.0), "4 values", id="too-few-values"),
    ],
)
def test_malformed_bboxes_are_rejected_with_a_specific_reason(bbox, expected):
    with pytest.raises(InvalidAreaOfInterest) as err:
        AreaOfInterest(name="bad", label="Bad", bbox=bbox)

    assert expected in str(err.value)


def test_missing_config_file_is_a_clear_error(tmp_path):
    with pytest.raises(RegionConfigError, match="No region config at"):
        load_regions(tmp_path / "nope.yml")


def test_config_without_a_regions_key_is_rejected(tmp_path):
    path = tmp_path / "regions.yml"
    path.write_text("areas:\n  adirondacks:\n    bbox: [-75, 43, -73, 44]\n")

    with pytest.raises(RegionConfigError, match="top-level 'regions:'"):
        load_regions(path)


def test_region_missing_a_bbox_is_rejected(tmp_path):
    path = tmp_path / "regions.yml"
    path.write_text("regions:\n  adirondacks:\n    label: Adirondack Park\n")

    with pytest.raises(RegionConfigError, match="missing 'bbox'"):
        load_regions(path)


def test_a_custom_config_can_add_a_region_without_touching_code(tmp_path):
    """Criterion: a new area of interest is a config change, not a code change."""
    path = tmp_path / "regions.yml"
    path.write_text(
        "regions:\n"
        "  north-cascades:\n"
        "    label: North Cascades\n"
        "    bbox: [-121.8, 48.3, -120.5, 49.0]\n"
        "    states: [WA]\n"
    )

    areas = load_regions(path)

    assert list(areas) == ["north-cascades"]
    assert areas["north-cascades"].states == ("WA",)
    assert get_region("north-cascades", path).label == "North Cascades"
