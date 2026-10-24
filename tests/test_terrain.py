"""
Terrain pipeline tests (TM05-141).

- Registry loading, and the errors a bad tools.yml raises.
- Classification thresholds: pooling, sun, shelter, view.
- Tiling: cores partition the region, and a neighbourhood tool computed tile by tile with
  overlap equals the untiled result at every core cell (no seams).
- Per-site fact mapping from a real GDAL raster.
- The whole pipeline end to end, in-process, on a synthetic DEM with a fake GeoLibre:
  facts, zones and provenance written; a re-run is idempotent and resumes.

The real GeoLibre runtime isn't used in CI (it is a 24 MB download); its behaviour was
measured in the TM05-139 spike and in the region run recorded in docs/terrain-analysis.md.
"""

import dataclasses
import json
import math
from pathlib import Path

import pytest
import yaml
from django.contrib.gis.gdal import CoordTransform, GDALRaster, SpatialReference
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.utils import timezone

from geodata.models import Campsite, WaterFeature
from terrain import dem, grid, mappers, pipeline, registry, runtime, worker
from terrain.models import TerrainFacts, TerrainRun, TerrainTile, TerrainZone

REAL = registry.load()


# --- registry -----------------------------------------------------------------------


def test_the_shipped_registry_loads():
    assert set(REAL.tools) == {"wetness", "sink", "slope", "aspect", "position", "viewshed"}
    assert REAL.tools["wetness"].grid.resolution_m == 45
    assert REAL.tools["wetness"].grid.tile_cells is None  # whole region in one piece
    assert [s.tool for s in REAL.tools["wetness"].steps] == [
        "fill_depressions",
        "dinf_flow_accum",
        "slope",
        "wetness_index",
    ]
    assert REAL.tools["position"].zones.layer == "exposure"
    assert REAL.tools["wetness"].zones.layer == "pooling-risk"
    assert REAL.tools["viewshed"].per_site == {"radius_m": 10000.0, "eye_height_m": 1.7}
    assert len(REAL.digest) == 16


def test_every_registered_geolibre_tool_is_in_the_v1_7_1_manifest():
    """The ids were checked against list_tools() for the runtime this registry pins."""
    known = {
        "fill_depressions", "dinf_flow_accum", "slope", "wetness_index", "depth_in_sink",
        "aspect", "deviation_from_mean_elevation", "viewshed",
    }  # fmt: skip
    used = {name for tool in REAL.tools.values() for name in tool.geolibre_tools}
    assert used <= known


def write_registry(tmp_path, change) -> Path:
    raw = yaml.safe_load(registry.DEFAULT_PATH.read_text())
    change(raw)
    path = tmp_path / "tools.yml"
    path.write_text(yaml.safe_dump(raw))
    return path


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: r["tools"]["sink"].update(grid="nowhere"), "unknown grid 'nowhere'"),
        (
            lambda r: r["tools"]["wetness"]["steps"][1]["args"].update(input="{later}"),
            "'{later}' is not the dem or an earlier step",
        ),
        (
            lambda r: r["tools"]["slope"]["facts"]["slope_deg"].update(sample="mode"),
            "unknown sample 'mode'",
        ),
        (
            lambda r: r["tools"]["position"]["zones"]["classes"].append({"class": "x", "min": 0}),
            "strictly increasing",
        ),
        (lambda r: r["tools"]["aspect"].pop("facts"), "produces nothing"),
        (
            lambda r: r["tools"]["aspect"]["facts"].update(slope_deg={"sample": "median"}),
            "facts named by more than one tool",
        ),
        (lambda r: r["grids"]["fine"].update(resolution_m=0), "resolution_m must be positive"),
    ],
)
def test_a_malformed_registry_fails_at_load_with_the_tool_named(tmp_path, change, message):
    with pytest.raises(registry.RegistryError, match=message):
        registry.load(write_registry(tmp_path, change))


def test_adding_a_tool_is_a_config_entry(tmp_path):
    def add(raw):
        raw["tools"]["roughness"] = {
            "grid": "coarse",
            "steps": [{"id": "tri", "tool": "ruggedness_index", "args": {"input": "{dem}"}}],
            "facts": {"roughness": {"sample": "median", "radius_m": 30}},
        }

    loaded = registry.load(write_registry(tmp_path, add))
    assert loaded.tools["roughness"].facts[0].name == "roughness"
    assert loaded.digest != REAL.digest  # tile results won't be reused across configs


# --- classification thresholds ------------------------------------------------------

POOLING = REAL.classify["pooling"]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"sink_depth_m": 0.0, "twi": 6.0}, "low"),
        ({"sink_depth_m": 0.1, "twi": 6.0}, "medium"),  # at the medium threshold
        ({"sink_depth_m": 3.0, "twi": 6.0}, "medium"),  # a deep hollow nothing drains into
        ({"sink_depth_m": 0.3, "twi": 10.0}, "high"),  # a hollow water drains into
        ({"sink_depth_m": 0.0, "twi": 10.0}, "medium"),
        ({"sink_depth_m": 0.0, "twi": 12.5}, "high"),
        ({"sink_depth_m": 0.15, "twi": 13.0}, "high"),  # wet low ground outranks a shallow hollow
        ({"twi": 9.99}, "low"),
        ({}, ""),
    ],
)
def test_pooling_thresholds(values, expected):
    level, reason = mappers.pooling(values, POOLING)
    assert level == expected
    assert bool(reason) == bool(expected)


def test_pooling_reasons_explain_the_class():
    assert "hollow about 0.4 m deep" in mappers.pooling({"sink_depth_m": 0.4, "twi": 5}, POOLING)[1]
    assert "drains into" in mappers.pooling({"sink_depth_m": 0.4, "twi": 11}, POOLING)[1]
    assert "wetness index 13.1" in mappers.pooling({"sink_depth_m": 0, "twi": 13.1}, POOLING)[1]
    assert "drains away" in mappers.pooling({"sink_depth_m": 0, "twi": 5.0}, POOLING)[1]


@pytest.mark.parametrize(
    ("aspect", "facing", "sun"),
    [
        (90, "east", "morning sun"),
        (100, "east", "morning sun"),
        (180, "south", "sun most of the day"),
        (350, "north", "little direct sun"),
        (10, "north", "little direct sun"),
        (250, "west", "afternoon and evening sun"),
        (225, "southwest", "afternoon sun"),
    ],
)
def test_aspect_becomes_a_facing_and_a_sun_label(aspect, facing, sun):
    assert mappers.sun({"aspect_deg": aspect, "slope_deg": 12}, REAL.classify["sun"]) == (
        facing,
        sun,
    )


def test_flat_ground_faces_nowhere():
    assert mappers.sun({"aspect_deg": 90, "slope_deg": 2}, REAL.classify["sun"])[0] == "flat"
    assert mappers.sun({}, REAL.classify["sun"]) == ("", "")


@pytest.mark.parametrize(
    ("dev", "expected"),
    [
        (1.4, "exposed"),
        (1.0, "exposed"),
        (0.3, "moderate"),
        (-0.5, "moderate"),
        (-0.8, "sheltered"),
    ],
)
def test_shelter_thresholds(dev, expected):
    assert mappers.shelter({"dev": dev}, REAL.classify["shelter"])[0] == expected


def test_view_stats_area_and_main_direction():
    # 21x21 cells of 30 m, site in the middle; a wedge opening to the east visible.
    width = height = 21

    def east(index):
        dx, dy = index % width - 10, 10 - index // width
        return dx > 0 and abs(dy) <= dx / 3

    visible = [1.0 if east(index) else 0.0 for index in range(width * height)]
    area, direction = mappers.view_stats(
        visible, width, height, 30, (10, 10), REAL.classify["view"]
    )
    assert area == pytest.approx(sum(map(east, range(width * height))) * 900 / 1e6)
    assert direction == "east"
    everywhere = [1.0] * (width * height)
    assert mappers.view_stats(everywhere, width, height, 30, (10, 10), REAL.classify["view"])[
        1
    ] == ("all around")


@pytest.mark.parametrize(
    ("values", "method", "expected"),
    [
        ([1, 2, 3, -999999], "median", 2),
        ([1, 2, 3], "max", 3),
        ([-999999, -999999], "median", None),
        ([350, 10], "circular_mean", 0.0),  # not 180
        ([-1, -1], "circular_mean", None),  # GeoLibre's flat-cell aspect
    ],
)
def test_sampling_ignores_nodata_and_wraps_angles(values, method, expected):
    result = mappers.sample(values, method, -999999)
    assert result == (pytest.approx(expected, abs=1e-6) if expected is not None else None)


# --- tiling ---------------------------------------------------------------------------


def test_tile_cores_partition_the_region_and_padding_stays_inside_it():
    region = (1000.0, 2000.0, 1000.0 + 95 * 10, 2000.0 + 61 * 10)
    tiles = grid.layout(region, 10, 20, 35)
    assert len(tiles) == 5 * 4
    covered = sum((t.core[2] - t.core[0]) * (t.core[3] - t.core[1]) for t in tiles)
    assert covered == pytest.approx((region[2] - region[0]) * (region[3] - region[1]))
    for t in tiles:
        assert t.padded[0] >= region[0] and t.padded[2] <= region[2]
        # Overlap rounds up to whole cells: 35 m is 4 cells of 10 m.
        if t.core[0] > region[0]:
            assert t.core[0] - t.padded[0] == 40
    # A point on a shared edge belongs to exactly one core.
    x, y = tiles[0].core[2], tiles[0].core[1] + 5
    assert sum(grid.contains(t.core, x, y) for t in tiles) == 1


def _mean_filter(values, width, height, radius):
    """A (2r+1)^2 neighbourhood mean, like DEV's moving window, clipped at the edges."""
    out = []
    for row in range(height):
        for column in range(width):
            cells = [
                values[r * width + c]
                for r in range(max(0, row - radius), min(height, row + radius + 1))
                for c in range(max(0, column - radius), min(width, column + radius + 1))
            ]
            out.append(sum(cells) / len(cells))
    return out


def test_tiling_with_overlap_has_no_seams():
    resolution, width, height, radius = 10.0, 47, 38, 3
    region = (0.0, 0.0, width * resolution, height * resolution)
    surface = [math.sin(i * 0.37) * 50 + (i % width) * 2.0 for i in range(width * height)]
    untiled = _mean_filter(surface, width, height, radius)

    stitched = [None] * (width * height)
    for tile in grid.layout(region, resolution, 16, radius * resolution):
        pw, ph = grid.cells(tile.padded, resolution)
        left = round(tile.padded[0] / resolution)
        top = round((region[3] - tile.padded[3]) / resolution)
        padded = [surface[(top + r) * width + left + c] for r in range(ph) for c in range(pw)]
        result = _mean_filter(padded, pw, ph, radius)
        column, row, cw, ch = grid.window(tile.padded, tile.core, resolution)
        for r in range(ch):
            for c in range(cw):
                stitched[(top + row + r) * width + left + column + c] = result[
                    (row + r) * pw + column + c
                ]
    assert None not in stitched
    assert stitched == pytest.approx(untiled)

    # Without the overlap, the tile edges are wrong: this test would catch seams.
    seamed = [None] * (width * height)
    for tile in grid.layout(region, resolution, 16, 0):
        pw, ph = grid.cells(tile.padded, resolution)
        left = round(tile.padded[0] / resolution)
        top = round((region[3] - tile.padded[3]) / resolution)
        padded = [surface[(top + r) * width + left + c] for r in range(ph) for c in range(pw)]
        result = _mean_filter(padded, pw, ph, radius)
        for i, value in enumerate(result):
            seamed[(top + i // pw) * width + left + i % pw] = value
    assert seamed != pytest.approx(untiled)


def test_region_bounds_contain_the_projected_bbox():
    bbox = (-74.2, 44.0, -73.9, 44.2)
    xmin, ymin, xmax, ymax = dem.region_bounds_m(bbox, 5070)
    for lon, lat in [(-74.2, 44.0), (-73.9, 44.2), (-74.05, 44.2), (-74.2, 44.1)]:
        point = Point(lon, lat, srid=4326)
        point.transform(5070)
        assert xmin - 1e-6 <= point.x <= xmax + 1e-6 and ymin - 1e-6 <= point.y <= ymax + 1e-6


def test_source_tiles_cover_the_adirondacks():
    assert sorted(dem.source_tiles((-75.40, 43.00, -73.30, 44.90))) == [
        "n44w074", "n44w075", "n44w076", "n45w074", "n45w075", "n45w076",
    ]  # fmt: skip


# --- a synthetic DEM and a fake GeoLibre ---------------------------------------------

NODATA = -999999.0
DEM_RES = 30.0
# A 2.4 km square in EPSG:5070 near Marcy Dam: a bowl with a pit in its centre.
DEM_ORIGIN = (1739000.0, 2558000.0)
DEM_CELLS = 80
CENTRE_M = DEM_CELLS * DEM_RES / 2


def _bowl(x, y):
    cx, cy = DEM_ORIGIN[0] + CENTRE_M, DEM_ORIGIN[1] - CENTRE_M
    r = math.hypot(x - cx, y - cy)
    return 600 + r * 0.05 - (2.0 if r < 60 else 0.0) + 40 * math.sin((x - cx) / 900)


def write_dem(path: Path) -> None:
    values = [
        _bowl(DEM_ORIGIN[0] + (c + 0.5) * DEM_RES, DEM_ORIGIN[1] - (r + 0.5) * DEM_RES)
        for r in range(DEM_CELLS)
        for c in range(DEM_CELLS)
    ]
    GDALRaster(
        {
            "name": str(path),
            "driver": "GTiff",
            "srid": 5070,
            "width": DEM_CELLS,
            "height": DEM_CELLS,
            "origin": list(DEM_ORIGIN),
            "scale": [DEM_RES, -DEM_RES],
            "datatype": 6,
            "bands": [{"data": values, "nodata_value": NODATA}],
        }
    )


def _raster(data: bytes) -> GDALRaster:
    return GDALRaster(data)


def _like(src: GDALRaster, values, name: str) -> bytes:
    out = GDALRaster(
        {
            "name": f"/vsimem/fake-{name}.tif",
            "driver": "GTiff",
            "srid": src.srid,
            "width": src.width,
            "height": src.height,
            "origin": [src.origin.x, src.origin.y],
            "scale": [src.scale.x, src.scale.y],
            "datatype": 6,
            "bands": [{"data": values, "nodata_value": NODATA}],
        }
    )
    return bytes(out.vsi_buffer)


class FakeGeoLibre:
    """Stands in for runtime.run: each tool is a small pure-Python raster operation, so
    the pipeline's plumbing (chains, tiles, sampling, zones, storage) is what's tested."""

    def __init__(self):
        self.calls = []

    def __call__(self, wasm, tool, args, inputs):
        self.calls.append(tool)
        if tool == "raster_to_vector_polygons":
            return self._polygons(inputs[Path(args["input"]).name])
        source_arg = next(k for k in ("input", "dem", "sca") if k in args)
        src = _raster(inputs[Path(args[source_arg]).name])
        values = src.bands[0].data()
        if tool == "reclass":
            rows = [list(map(float, row.split(","))) for row in args["reclass_values"].split(";")]
            values = [
                NODATA if v == NODATA else next(n for n, lo, hi in rows if lo <= v < hi)
                for v in values
            ]
        elif tool == "viewshed":
            values = [1.0] * len(values)
        elif tool == "wetness_index":
            # A deterministic stand-in: high in the middle of the bowl.
            w = src.width
            values = [
                14.0
                if abs(i % w - w / 2) < w / 8 and abs(i // w - src.height / 2) < src.height / 8
                else 6.0
                for i in range(len(values))
            ]
        elif tool == "depth_in_sink":
            values = [0.5 if v < 602 else 0.0 for v in values]
        elif tool == "aspect":
            values = [90.0] * len(values)
        elif tool == "deviation_from_mean_elevation":
            values = [(v - 620) / 20 for v in values]
        output = Path(args.get("output", "/work/out.tif")).name
        return runtime.Result(
            {output: _like(src, values, f"{tool}-{len(self.calls)}")}, [], 1 << 20
        )

    @staticmethod
    def _polygons(data):
        """One rectangle per run of equal non-zero cells along a row."""
        src = _raster(data)
        values, w = src.bands[0].data(), src.width
        to_wgs84 = CoordTransform(SpatialReference(src.srid), SpatialReference(4326))
        features = []
        for row in range(src.height):
            column = 0
            while column < w:
                v = values[row * w + column]
                end = column + 1
                while end < w and values[row * w + end] == v:
                    end += 1
                if v not in (None, NODATA) and v >= 0.5:
                    x0 = src.origin.x + column * src.scale.x
                    y0 = src.origin.y + row * src.scale.y
                    x1 = x0 + (end - column) * src.scale.x
                    run = Polygon.from_bbox((x0, y0 + src.scale.y, x1, y0))
                    run.srid = src.srid
                    run.transform(to_wgs84)
                    features.append(
                        {
                            "type": "Feature",
                            "properties": {"VALUE": int(v)},
                            "geometry": json.loads(run.json),
                        }
                    )
                column = end
        body = json.dumps({"type": "FeatureCollection", "features": features}).encode()
        return runtime.Result({"zones.geojson": body, "visible.geojson": body}, [], 1 << 20)


@pytest.fixture
def synthetic(tmp_path, monkeypatch, settings):
    """The pipeline wired to a synthetic DEM, a fake GeoLibre and a small region."""
    dem_path = tmp_path / "dem.tif"
    write_dem(dem_path)
    corner = Point(DEM_ORIGIN[0], DEM_ORIGIN[1], srid=5070)
    far = Point(DEM_ORIGIN[0] + DEM_CELLS * DEM_RES, DEM_ORIGIN[1] - DEM_CELLS * DEM_RES, srid=5070)
    corner.transform(4326)
    far.transform(4326)
    bbox = (corner.x + 0.002, far.y + 0.002, far.x - 0.002, corner.y - 0.002)

    regions = tmp_path / "regions.yml"
    regions.write_text(
        yaml.safe_dump({"regions": {"testland": {"label": "T", "bbox": list(bbox)}}})
    )
    from pipeline import regions as regions_module

    real_get_region = regions_module.get_region
    monkeypatch.setattr(pipeline, "get_region", lambda name: real_get_region(name, regions))

    source = dem.Source("testland", ["synthetic"], tmp_path, {"synthetic": {"bytes": 1}})
    monkeypatch.setattr(runtime, "runtime_path", lambda cfg: tmp_path / "fake.wasm")
    monkeypatch.setattr(runtime, "prepare", lambda path: None)
    monkeypatch.setattr(dem, "fetch", lambda *a, **k: source)
    monkeypatch.setattr(dem, "build_vrt", lambda s: dem_path)
    monkeypatch.setenv("TERRAIN_CACHE_DIR", str(tmp_path / "cache"))
    fake = FakeGeoLibre()
    monkeypatch.setattr(runtime, "run", fake)

    # Small grids so the 2.4 km square still has several tiles.
    raw = yaml.safe_load(registry.DEFAULT_PATH.read_text())
    raw["grids"]["coarse"].update(tile_cells=30, overlap_m=150)
    raw["grids"]["fine"].update(resolution_m=30, tile_cells=30, overlap_m=150)
    raw["grids"]["hydrology"]["resolution_m"] = 30
    raw["tools"]["viewshed"]["per_site"]["radius_m"] = 300
    raw["tools"]["wetness"]["zones"]["min_area_m2"] = 0
    raw["tools"]["position"]["zones"]["min_area_m2"] = 0
    path = tmp_path / "tools.yml"
    path.write_text(yaml.safe_dump(raw))

    centre = Point(DEM_ORIGIN[0] + CENTRE_M, DEM_ORIGIN[1] - CENTRE_M, srid=5070)
    centre.transform(4326)
    edge = Point(DEM_ORIGIN[0] + 600, DEM_ORIGIN[1] - 700, srid=5070)
    edge.transform(4326)
    sites = [
        Campsite.objects.create(source="osm", source_id=f"node/{i}", name=name, geom=point)
        for i, (name, point) in enumerate([("Bowl", centre), ("Rim", edge)])
    ]
    lake = Polygon.from_bbox(
        (centre.x - 0.001, centre.y + 0.0005, centre.x + 0.001, centre.y + 0.0015)
    )
    lake.srid = 4326
    WaterFeature.objects.create(
        source="nhd", source_id="lake/1", name="Test Pond", geom=lake, feature_type="lake"
    )
    return {"registry": registry.load(path), "sites": sites, "fake": fake}


@pytest.mark.django_db
def test_the_pipeline_writes_facts_zones_and_provenance(synthetic):
    reg = synthetic["registry"]
    run = pipeline.run("testland", reg, workers=0, log=lambda *_: None)

    bowl, rim = (TerrainFacts.objects.get(campsite=s) for s in synthetic["sites"])
    assert bowl.values["sink_depth_m"] == pytest.approx(0.5)
    assert bowl.pooling == "high" and "wetness index 14.0" in bowl.pooling_reason
    assert rim.values["twi"] == pytest.approx(6.0)
    assert rim.pooling == "low"
    assert bowl.facing == "east" and bowl.sun == "morning sun"
    assert bowl.shelter in {"sheltered", "moderate", "exposed"}
    assert bowl.view_area_km2 > 0 and bowl.viewshed is not None
    assert bowl.water_view is True  # the pond sits inside its (all-visible) viewshed

    pooling = TerrainZone.objects.filter(region="testland", layer="pooling-risk", tile="")
    assert pooling.exists()
    assert (
        not TerrainZone.objects.filter(region="testland", layer="pooling-risk")
        .exclude(zone_class="high")
        .exists()
    )
    # Served zones are the tile pieces, simplified; the bowl's wet centre crosses tiles.
    assert pooling.count() >= 2

    assert run.finished_at is not None
    assert run.config_digest == reg.digest
    assert run.counts["coverage"]["pooling"] == 2
    assert set(run.timings["tools"]) == set(reg.tools)
    assert run.tool_versions["runtime_sha256"] == reg.runtime["sha256"]
    assert run.counts["zones"]["pooling-risk"] == {"high": pooling.count()}


@pytest.mark.django_db
def test_a_rerun_is_idempotent_and_reuses_finished_tiles(synthetic):
    reg = synthetic["registry"]
    pipeline.run("testland", reg, workers=0, log=lambda *_: None)
    first = {
        "facts": list(
            TerrainFacts.objects.order_by("pk").values("pk", "values", "pooling", "facing")
        ),
        "zones": sorted(
            (z.layer, z.zone_class, round(z.area_m2)) for z in TerrainZone.objects.filter(tile="")
        ),
        "tiles": TerrainTile.objects.count(),
    }
    calls = len(synthetic["fake"].calls)

    second_run = pipeline.run("testland", reg, workers=0, log=lambda *_: None)
    assert len(synthetic["fake"].calls) == calls  # no tool ran again
    assert sum(t["skipped"] for t in second_run.timings["tools"].values()) == first["tiles"]
    assert (
        list(TerrainFacts.objects.order_by("pk").values("pk", "values", "pooling", "facing"))
        == (first["facts"])
    )
    assert (
        sorted(
            (z.layer, z.zone_class, round(z.area_m2)) for z in TerrainZone.objects.filter(tile="")
        )
        == first["zones"]
    )
    assert TerrainTile.objects.count() == first["tiles"]
    assert TerrainRun.objects.count() == 2


@pytest.mark.django_db
def test_an_interrupted_run_resumes_from_the_finished_tiles(synthetic):
    reg = synthetic["registry"]
    pipeline.run("testland", reg, workers=0, log=lambda *_: None)
    total = TerrainTile.objects.count()
    # Lose two tiles, as if the run had stopped before them.
    lost = list(TerrainTile.objects.order_by("pk")[:2])
    TerrainTile.objects.filter(pk__in=[t.pk for t in lost]).delete()
    run = pipeline.run("testland", reg, workers=0, log=lambda *_: None)
    assert sum(t["tasks"] for t in run.timings["tools"].values()) == 2
    assert TerrainTile.objects.count() == total


@pytest.mark.django_db
def test_fresh_recomputes_every_tile(synthetic):
    reg = synthetic["registry"]
    pipeline.run("testland", reg, workers=0, log=lambda *_: None)
    calls = len(synthetic["fake"].calls)
    pipeline.run("testland", reg, workers=0, fresh=True, log=lambda *_: None)
    assert len(synthetic["fake"].calls) == 2 * calls


def test_reclass_rows_cover_every_value():
    rows = worker.reclass_values(REAL.tools["position"])
    assert rows == "0,-1e30,1.0;1,1.0,1e+30"


def test_chains_pass_each_step_its_inputs(tmp_path, monkeypatch):
    seen = []

    def fake(wasm, tool, args, inputs):
        seen.append((tool, dict(args), sorted(inputs)))
        output = Path(args["output"]).name
        return runtime.Result({output: b"x"}, [], 2 << 20)

    monkeypatch.setattr(runtime, "run", fake)
    _, peak = worker.run_chain(tmp_path / "w.wasm", REAL.tools["wetness"], b"dem")
    assert [s[0] for s in seen] == ["fill_depressions", "dinf_flow_accum", "slope", "wetness_index"]
    assert seen[1][1]["input"] == "/work/filled.tif" and seen[1][2] == ["dem.tif", "filled.tif"]
    assert seen[3][1] == {
        "sca": "/work/sca.tif",
        "slope": "/work/slope.tif",
        "output": "/work/twi.tif",
    }
    assert seen[3][2] == ["dem.tif", "sca.tif", "slope.tif"]
    assert peak == 2 << 20


def test_runtime_rejects_a_wasm_with_the_wrong_checksum(tmp_path, monkeypatch):
    wasm = tmp_path / "geolibre.wasm"
    wasm.write_bytes(b"\x00asm not really")
    monkeypatch.setenv("GEOLIBRE_WASM", str(wasm))
    with pytest.raises(RuntimeError, match="expected"):
        runtime.runtime_path(REAL.runtime)
    monkeypatch.setenv("GEOLIBRE_WASM", str(tmp_path / "missing.wasm"))
    with pytest.raises(FileNotFoundError):
        runtime.runtime_path(REAL.runtime)


def test_changing_a_class_threshold_reuses_every_tile(tmp_path):
    def tweak(raw):
        raw["classify"]["shelter"]["exposed_from"] = 1.2

    assert registry.load(write_registry(tmp_path, tweak)).digest == REAL.digest


@pytest.mark.django_db
def test_merge_simplifies_pieces_and_drops_slivers():
    def square(x, y, size):
        shape = Polygon.from_bbox((x, y, x + size, y + size))
        shape.srid = 5070
        shape.transform(4326)
        return MultiPolygon(shape, srid=4326)

    x0, y0 = DEM_ORIGIN[0], DEM_ORIGIN[1] - 2000
    for tile, x, size in (("0-0", x0, 200.0), ("1-0", x0 + 1000, 50.0)):  # 4 ha, 0.25 ha
        TerrainZone.objects.create(
            region="testland",
            layer="exposure",
            zone_class="high",
            tile=tile,
            area_m2=0,
            geom=square(x, y0, size),
        )
    run = TerrainRun.objects.create(
        region="testland", started_at=timezone.now(), config_digest="x", dem_digest="y"
    )
    tool = registry.load().tools["position"]  # min_area_m2 50000 -> lower it to 1 ha
    tool = dataclasses.replace(tool, zones=dataclasses.replace(tool.zones, min_area_m2=10000))
    assert pipeline.merge_zones(run, "testland", tool) == {"high": 1}
    [kept] = TerrainZone.objects.filter(region="testland", layer="exposure", tile="")
    assert kept.area_m2 == pytest.approx(40000, rel=0.01)
    # Merging again replaces, never duplicates.
    pipeline.merge_zones(run, "testland", tool)
    assert TerrainZone.objects.filter(region="testland", layer="exposure", tile="").count() == 1


# --- the runtime and the DEM source, without the network or the real WASM -----------

# A minimal WASI command: writes "ok" to stdout, then exits with the code in its name.
WAT = """
(module
  (import "wasi_snapshot_preview1" "fd_write" (func $fd_write (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "proc_exit" (func $proc_exit (param i32)))
  (memory (export "memory") 1)
  (data (i32.const 16) "ok\\n")
  (func (export "_start")
    (i32.store (i32.const 0) (i32.const 16))
    (i32.store (i32.const 4) (i32.const 3))
    (drop (call $fd_write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 8)))
    (call $proc_exit (i32.const CODE))))
"""


def _wasm(tmp_path, code: int) -> Path:
    import wasmtime

    path = tmp_path / f"exit{code}.wasm"
    path.write_bytes(wasmtime.wat2wasm(WAT.replace("CODE", str(code))))
    return path


def test_runtime_runs_a_wasi_module_and_reports_its_memory(tmp_path):
    result = runtime.run(
        _wasm(tmp_path, 0), "any", {"input": "/work/a.tif", "flag": True}, {"a.tif": b"x"}
    )
    assert result.log == ["ok"]
    assert result.files == {}  # inputs are not echoed back
    assert result.peak_memory == 65536  # one WASM page
    # The compiled module was cached beside it for the next process.
    assert list(tmp_path.glob("exit0.wasm.wasmtime-*.cwasm"))


def test_runtime_raises_with_the_tools_output_on_failure(tmp_path):
    with pytest.raises(runtime.ToolFailed, match="slope exited 3: ok"):
        runtime.run(_wasm(tmp_path, 3), "slope", {}, {})


def test_runtime_fetches_the_pinned_runtime_once_and_checks_it(tmp_path, monkeypatch):
    import hashlib

    body = b"\\x00asm fake runtime"
    pinned = {
        "url": "https://example.test/geolibre-cli-v9.wasm",
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    monkeypatch.delenv("GEOLIBRE_WASM", raising=False)
    monkeypatch.setenv("TERRAIN_CACHE_DIR", str(tmp_path))
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            calls.append(1)
            return body

    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *a, **k: Response())
    path = runtime.runtime_path(pinned)
    assert path == tmp_path / "geolibre" / "geolibre-cli-v9.wasm" and path.read_bytes() == body
    runtime.runtime_path(pinned)
    assert len(calls) == 1  # cached
    with pytest.raises(RuntimeError, match="expected"):
        runtime.runtime_path({**pinned, "sha256": "0" * 64})


def _source_tile(path: Path, west: int, north: int, value: float) -> None:
    """A tiny 1x1 degree tile in NAD83, like a 3DEP one but 12x12 cells."""
    GDALRaster(
        {
            "name": str(path),
            "driver": "GTiff",
            "srid": 4269,
            "width": 12,
            "height": 12,
            "origin": [west, north],
            "scale": [1 / 12, -1 / 12],
            "datatype": 6,
            "bands": [{"data": [value] * 144, "nodata_value": NODATA}],
        }
    )


def test_fetch_downloads_changed_tiles_and_builds_one_vrt(tmp_path, monkeypatch):
    monkeypatch.setenv("TERRAIN_CACHE_DIR", str(tmp_path))
    remote = {
        "n45w074": {"last_modified": "Mon", "bytes": 10},
        "n45w075": {"last_modified": "Mon", "bytes": 10},
    }
    downloads = []

    def download(url, path):
        downloads.append(url)
        tile = url.rsplit("_", 1)[1].removesuffix(".tif")
        _source_tile(path, -int(tile[4:]), int(tile[1:3]), 500.0 if tile == "n45w074" else 700.0)

    monkeypatch.setattr(
        dem, "_head", lambda url: remote[url.rsplit("_", 1)[1].removesuffix(".tif")]
    )
    monkeypatch.setattr(dem, "_download", download)
    url = "https://example.test/{tile}/USGS_13_{tile}.tif"
    bbox = (-74.9, 44.1, -73.1, 44.9)

    source = dem.fetch("testland", bbox, url, log=lambda *_: None)
    assert sorted(source.names) == ["n45w074", "n45w075"] and len(downloads) == 2
    assert source.provenance(url)["tiles"]["n45w074"]["url"].endswith("USGS_13_n45w074.tif")

    again = dem.fetch("testland", bbox, url, log=lambda *_: None)
    assert len(downloads) == 2 and again.digest == source.digest  # nothing changed

    remote["n45w074"] = {"last_modified": "Tue", "bytes": 11}
    changed = dem.fetch("testland", bbox, url, log=lambda *_: None)
    assert len(downloads) == 3 and changed.digest != source.digest

    vrt = GDALRaster(str(dem.build_vrt(changed)))
    assert (vrt.width, vrt.height) == (24, 12)
    assert vrt.bands[0].data(offset=(2, 2), size=(1, 1))[0] == 700.0  # the western tile
    assert vrt.bands[0].data(offset=(20, 2), size=(1, 1))[0] == 500.0

    # Offline, the tiles on disk are used.
    def offline(url):
        raise OSError("no network")

    monkeypatch.setattr(dem, "_head", offline)
    assert dem.fetch("testland", bbox, url, log=lambda *_: None).digest == changed.digest
