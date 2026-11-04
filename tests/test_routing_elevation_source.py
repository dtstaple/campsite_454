"""
The graph build's elevation source (TM05-149): the terrain pipeline's cached 3DEP mosaic
when it is on disk, 3DEP's getSamples when it isn't.

The DEM here is synthetic: two 1x1 degree NAD83 tiles of 120x120 cells, like 3DEP's
but coarse, holding a plane that rises 100 m per degree east and 50 m per degree north.
Bilinear sampling reproduces a plane exactly, so every value has a known answer.
"""

import json
from pathlib import Path

import pytest
from django.contrib.gis.gdal import GDALRaster
from django.contrib.gis.geos import Point

from routing import elevation_source
from routing.elevation_source import MosaicSampler, cached_source, choose
from terrain import dem

NODATA = -999999.0
CELLS = 120
BBOX = (-74.9, 44.1, -73.1, 44.9)  # tiles n45w075 and n45w074


def plane(lon: float, lat: float) -> float:
    return 1000.0 + 100.0 * (lon + 75.0) + 50.0 * (lat - 44.0)


def write_tile(path: Path, west: int, north: int, hole: bool = False) -> None:
    step = 1 / CELLS
    values = []
    for r in range(CELLS):
        for c in range(CELLS):
            lon, lat = west + (c + 0.5) * step, north - (r + 0.5) * step
            empty = hole and 50 <= r < 70 and 50 <= c < 70
            values.append(NODATA if empty else plane(lon, lat))
    GDALRaster(
        {
            "name": str(path),
            "driver": "GTiff",
            "srid": 4269,
            "width": CELLS,
            "height": CELLS,
            "origin": [west, north],
            "scale": [step, -step],
            "datatype": 6,
            "bands": [{"data": values, "nodata_value": NODATA}],
        }
    )


@pytest.fixture
def terrain_cache(tmp_path, monkeypatch):
    """The terrain pipeline's cache, as `make terrain` leaves it, in a temporary dir."""
    monkeypatch.setenv("TERRAIN_CACHE_DIR", str(tmp_path))
    tiles = tmp_path / "3dep-13"
    tiles.mkdir()

    def make(hole: bool = False, names=("n45w075", "n45w074")):
        known = {}
        for name in names:
            write_tile(tiles / f"USGS_13_{name}.tif", -int(name[4:]), int(name[1:3]), hole)
            known[name] = {"last_modified": "Mon", "bytes": 1}
        (tiles / "signature.json").write_text(json.dumps(known))
        return tmp_path

    return make


def no_3dep(points):
    raise AssertionError(f"3DEP was asked for {len(points)} points")


@pytest.mark.unit
def test_no_cache_falls_back_to_3dep(tmp_path, monkeypatch):
    monkeypatch.setenv("TERRAIN_CACHE_DIR", str(tmp_path))
    choice = choose("testland", BBOX)
    assert choice.fetch is elevation_source.fetch_elevations
    assert choice.provenance == {"elevation_source": "3dep-getsamples"}
    with pytest.raises(FileNotFoundError, match="make terrain"):
        choose("testland", BBOX, mode="cache")


@pytest.mark.unit
def test_a_missing_tile_falls_back_to_3dep(terrain_cache):
    terrain_cache(names=("n45w075",))  # n45w074 was never downloaded
    assert cached_source("testland", BBOX) is None
    assert choose("testland", BBOX).provenance["elevation_source"] == "3dep-getsamples"


@pytest.mark.unit
def test_the_cached_mosaic_is_chosen_and_recorded(terrain_cache):
    root = terrain_cache()
    choice = choose("testland", BBOX)
    assert isinstance(choice.fetch, MosaicSampler)
    assert choice.provenance["elevation_source"] == "dem-cache"
    assert choice.provenance["tiles"] == ["n45w074", "n45w075"]
    # The VRT the terrain pipeline names by the tiles' digest, reused (not rebuilt).
    source = cached_source("testland", BBOX)
    vrt = root / "mosaic" / choice.provenance["mosaic"]
    assert vrt == dem.build_vrt(source) and choice.provenance["mosaic_digest"] == source.digest
    # --elevation 3dep ignores the cache, to measure the old path.
    assert choose("testland", BBOX, mode="3dep").fetch is elevation_source.fetch_elevations


@pytest.mark.unit
def test_the_mosaic_is_sampled_bilinearly_across_tiles(terrain_cache):
    terrain_cache()
    sampler = choose("testland", BBOX, mode="cache").fetch
    sampler.fallback = no_3dep
    # Points in both tiles, on the seam between them, and between cell centres.
    points = [
        Point(-74.5, 44.5, srid=4326),
        Point(-73.6123, 44.2877, srid=4326),
        Point(-74.0, 44.75, srid=4326),
        Point(-74.00417, 44.30833, srid=4326),
    ]
    values, source = sampler(points)
    for p, value in zip(points, values, strict=True):
        # NAD83 and WGS84 differ by about a metre here, far under a cell: the plane
        # rises 100 m per degree (~80 km), so a metre is about a millimetre of height.
        assert value == pytest.approx(plane(p.x, p.y), abs=0.01)
    assert source["fallback_points"] == 0
    assert any("mosaic" in d for d in source["datasets"])


@pytest.mark.unit
def test_points_the_mosaic_has_no_data_for_are_asked_of_3dep(terrain_cache):
    terrain_cache(hole=True)
    asked = []

    def fallback(points):
        asked.extend(points)
        return [123.0] * len(points), {"datasets": ["NY_LiDAR"]}

    sampler = choose("testland", BBOX, mode="cache").fetch
    sampler.fallback = fallback
    inside_hole = Point(-74.5, 44.5, srid=4326)  # the 20x20-cell hole in each tile
    edge_of_hole = Point(-74.5 - 9.6 / CELLS, 44.5, srid=4326)  # partly valid cells
    outside = Point(-76.5, 44.5, srid=4326)  # off the mosaic altogether
    values, source = sampler([inside_hole, edge_of_hole, outside])
    assert values[0] == 123.0 and values[2] == 123.0
    assert asked == [inside_hole, outside]
    # Next to the hole the valid neighbours carry the value: within a cell's rise.
    assert values[1] == pytest.approx(plane(edge_of_hole.x, edge_of_hole.y), abs=1.0)
    assert source["fallback_points"] == 2 and "NY_LiDAR" in source["datasets"]


@pytest.mark.unit
def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="auto, cache, 3dep"):
        choose("testland", BBOX, mode="lidar")
