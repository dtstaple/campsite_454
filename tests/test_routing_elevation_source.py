"""
The graph build's elevation source (TM05-149): the terrain pipeline's cached 3DEP mosaic
when it is on disk, 3DEP's getSamples when it isn't.

The DEM here is synthetic: 1x1 degree NAD83 tiles of 120x120 cells, like 3DEP's but
coarse, holding a plane. Bilinear sampling reproduces a plane exactly, so every value has
a known answer. The build tests use a steeper plane under a small trail network.
"""

import json
from pathlib import Path

import pytest
from django.contrib.gis.gdal import GDALRaster
from django.contrib.gis.geos import LineString, MultiLineString, Point

from analysis.analyses import elevation
from geodata.models import METRIC_SRID, Trail
from pipeline.regions import get_region
from routing import elevation_source
from routing.build import build_region
from routing.compare import EdgeRow, compare, load_rows
from routing.elevation_source import MosaicSampler, cached_source, choose
from routing.models import TrailEdge
from terrain import dem

NODATA = -999999.0
CELLS = 120
BBOX = (-74.9, 44.1, -73.1, 44.9)  # tiles n45w075 and n45w074


def plane(lon: float, lat: float) -> float:
    return 1000.0 + 100.0 * (lon + 75.0) + 50.0 * (lat - 44.0)


def steep(lon: float, lat: float) -> float:
    """About 0.09 m of rise per metre north: the build network's Ridge Trail climbs ~90 m."""
    return 500.0 + 10_000.0 * (lat - 44.0)


def write_tile(path: Path, west: int, north: int, hole: bool = False, height=plane) -> None:
    step = 1 / CELLS
    values = []
    for r in range(CELLS):
        for c in range(CELLS):
            lon, lat = west + (c + 0.5) * step, north - (r + 0.5) * step
            empty = hole and 50 <= r < 70 and 50 <= c < 70
            values.append(NODATA if empty else height(lon, lat))
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

    def make(hole: bool = False, names=("n45w075", "n45w074"), height=plane):
        known = {}
        for name in names:
            path = tiles / f"USGS_13_{name}.tif"
            write_tile(path, -int(name[4:]), int(name[1:3]), hole, height)
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


# --- the comparison ------------------------------------------------------------------------


def row(i, u, v, old, new, x=0.0):
    return EdgeRow(i, u, v, 1000.0, 1.0, (x, 0.0), (x + 1000.0, 0.0), old, new)


def two_ways(new_offset=0.0, steep_shift=0.0):
    """Two ways from node 1 to node 3: flat via 2, and a shorter climb via 4."""
    flat = [100.0] * 21
    hill = [100.0 + 10 * min(k, 20 - k) for k in range(21)]
    return [
        row(1, 1, 2, flat, [z + new_offset for z in flat]),
        row(2, 2, 3, flat, [z + new_offset for z in flat], x=1000.0),
        EdgeRow(
            3,
            1,
            4,
            900.0,
            1.0,
            (0.0, 0.0),
            (900.0, 50.0),
            hill,
            [z + new_offset + steep_shift * (k % 2) for k, z in enumerate(hill)],
        ),
        EdgeRow(
            4, 4, 3, 900.0, 1.0, (900.0, 50.0), (2000.0, 0.0), flat, [z + new_offset for z in flat]
        ),
    ]


@pytest.mark.unit
def test_the_same_elevations_compare_equal():
    report = compare(two_ways(), trips=10)
    assert report["ok"] and report["elevation_abs_diff_m"]["max"] == 0.0
    assert report["trips"] == 10 and report["trips_same_edges"] == 10
    assert report["total_ascent_diff_pct"] == 0.0


@pytest.mark.unit
def test_an_offset_fails_the_elevation_check_but_not_the_climb():
    report = compare(two_ways(new_offset=20.0), trips=10)
    assert not report["checks"]["sample_median_m"] and not report["checks"]["sample_p95_m"]
    assert report["checks"]["total_ascent_pct"] and report["checks"]["trip_time_p95_pct"]
    assert not report["ok"]


@pytest.mark.unit
def test_noise_that_adds_climb_fails_the_climb_and_route_checks():
    report = compare(two_ways(steep_shift=30.0), trips=10)
    assert not report["checks"]["total_ascent_pct"]
    assert report["total_ascent_m"]["mosaic"] > report["total_ascent_m"]["previous"]


# --- the build -----------------------------------------------------------------------------

ADIRONDACK_TILES = tuple(f"n{lat}w{lon:03d}" for lat in (44, 45) for lon in (74, 75, 76))
X0, Y0 = 1_770_000.0, 2_550_000.0  # the routing tests' network, near 44.06 N 73.63 W


def way(number, coords, nodes, name):
    line = LineString([(X0 + x, Y0 + y) for x, y in coords], srid=METRIC_SRID)
    return Trail.objects.create(
        source=Trail.Source.OSM,
        source_id=f"way/{number}",
        name=name,
        geom=MultiLineString(line.transform(4326, clone=True), srid=4326),
        length_m=line.length,
        osm_node_ids=nodes,
    )


@pytest.fixture
def small_network():
    way(1, [(0, 0), (500, 0), (1000, 0)], [100, 101, 102], "West Trail")
    way(2, [(1000, 0), (1000, 500), (1000, 1000)], [102, 201, 202], "Ridge Trail")
    way(3, [(1000, 0), (1500, 0), (2000, 0)], [102, 301, 302], "Valley Trail")
    way(4, [(2000, 0), (1500, 500), (1000, 1000)], [302, 401, 202], "Connector")


def ridge_rise_m():
    """What `steep` says the Ridge Trail climbs, from its two ends."""
    trail = Trail.objects.get(name="Ridge Trail")
    start, end = trail.geom[0][0], trail.geom[0][-1]
    return steep(*end) - steep(*start)


def getsamples_of(height, offset_m=0.0):
    """A stand-in for 3DEP's getSamples (analysis.analyses.elevation.post_samples)."""

    def post_samples(points):
        return {
            "samples": [
                {"locationId": i, "value": str(height(p.x, p.y) + offset_m)}
                for i, p in enumerate(points)
            ]
        }

    return post_samples


def no_getsamples(points):
    raise AssertionError(f"3DEP getSamples was asked for {len(points)} points")


@pytest.mark.django_db
@pytest.mark.integration
def test_the_build_samples_the_cached_mosaic_without_asking_3dep(
    terrain_cache, small_network, monkeypatch
):
    terrain_cache(names=ADIRONDACK_TILES, height=steep)
    monkeypatch.setattr(elevation, "post_samples", no_getsamples)
    build = build_region("adirondacks", workers=2, log=lambda *_: None)
    assert build.provenance["elevation_source"] == "dem-cache"
    assert build.provenance["tiles"] == sorted(ADIRONDACK_TILES)
    assert build.elevation_samples > 0 and build.elevation_nodata == 0
    ridge = TrailEdge.objects.get(name="Ridge Trail")
    assert ridge.ascent_m == pytest.approx(ridge_rise_m(), abs=0.5) and ridge.ascent_m > 80
    assert ridge.descent_m == pytest.approx(0, abs=0.1)


@pytest.mark.django_db
@pytest.mark.integration
def test_without_the_cache_the_build_asks_3dep(tmp_path, small_network, monkeypatch):
    monkeypatch.setenv("TERRAIN_CACHE_DIR", str(tmp_path))  # empty: no tiles downloaded
    monkeypatch.setattr(elevation, "post_samples", getsamples_of(steep))
    build = build_region("adirondacks", workers=1, log=lambda *_: None)
    assert build.provenance["elevation_source"] == "3dep-getsamples"
    ridge = TrailEdge.objects.get(name="Ridge Trail")
    assert ridge.ascent_m == pytest.approx(ridge_rise_m(), abs=0.5)


@pytest.mark.django_db
@pytest.mark.integration
def test_a_3dep_build_and_the_mosaic_agree_within_tolerance(
    terrain_cache, small_network, monkeypatch
):
    terrain_cache(names=ADIRONDACK_TILES, height=steep)
    # The previous build: 3DEP getSamples, sitting half a metre off the mosaic.
    monkeypatch.setattr(elevation, "post_samples", getsamples_of(steep, offset_m=0.5))
    build_region("adirondacks", elevation="3dep", workers=1, log=lambda *_: None)
    monkeypatch.setattr(elevation, "post_samples", no_getsamples)
    report = compare(
        load_rows(
            "adirondacks", choose("adirondacks", get_region("adirondacks").bbox, "cache").fetch
        )
    )
    assert report["ok"], report
    assert report["samples_without_mosaic_data"] == 0
    assert report["elevation_abs_diff_m"]["median"] == pytest.approx(0.5, abs=0.05)
    assert report["trips"] == 50 and report["trips_same_edges"] == 50
