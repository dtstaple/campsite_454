"""
The worker side of the terrain pipeline (TM05-141): one tool on one tile, or the
viewshed for a batch of sites.

These run in spawned worker processes, and return plain data. This module must not
import Django models: a spawned worker unpickles these functions by importing their
module, and that happens before `_worker_init` has set Django up. GeoDjango's GDAL
bindings only need DJANGO_SETTINGS_MODULE, which the worker inherits.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from django.contrib.gis.gdal import GDALRaster

from terrain import dem, mappers, runtime
from terrain.grid import Tile
from terrain.registry import Tool

#: Zones are polygonised in pieces of at most this many cells a side:
#: raster_to_vector_polygons needs about 145 bytes per cell.
ZONE_CHUNK_CELLS = 2500


def init() -> None:
    # Spawned workers need Django configured for GeoDjango's GDAL bindings; they never
    # open a database connection.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def _arg(value, outputs: set[str]):
    if isinstance(value, str):
        for name in outputs:
            value = value.replace(f"{{{name}}}", f"/work/{name}.tif")
    return value


def run_chain(wasm: Path, tool: Tool, dem_tif: bytes) -> tuple[bytes, int]:
    """A tool's GeoLibre steps on one DEM tile: (the last step's raster, peak memory)."""
    files = {"dem.tif": dem_tif}
    peak = 0
    for step in tool.steps:
        produced = {name.removesuffix(".tif") for name in files}
        args = {key: _arg(value, produced) for key, value in step.args.items()}
        if "output" not in args and not any(k.endswith("_output") for k in args):
            args["output"] = f"/work/{step.id}.tif"
        needed = {"dem.tif"} | {f"{ref}.tif" for ref in step.references()}
        result = runtime.run(wasm, step.tool, args, {n: files[n] for n in needed if n in files})
        peak = max(peak, result.peak_memory)
        files[f"{step.id}.tif"] = result.files[f"{step.id}.tif"]
    return files[f"{tool.steps[-1].id}.tif"], peak


def _cells_around(band, origin, resolution, x, y, radius_m, width, height):
    column = int((x - origin[0]) // resolution)
    row = int((origin[1] - y) // resolution)
    r = max(0, round(radius_m / resolution))
    left, top = max(0, column - r), max(0, row - r)
    right, bottom = min(width, column + r + 1), min(height, row + r + 1)
    if right <= left or bottom <= top:
        return []
    return band.data(offset=(left, top), size=(right - left, bottom - top))


def sample_sites(raster: GDALRaster, tool: Tool, sites) -> dict[int, dict]:
    band = raster.bands[0]
    origin = (raster.origin.x, raster.origin.y)
    resolution = raster.scale.x
    out: dict[int, dict] = {}
    for site_id, x, y in sites:
        values = {}
        for fact in tool.facts:
            cells = _cells_around(
                band, origin, resolution, x, y, fact.radius_m, raster.width, raster.height
            )
            value = mappers.sample(cells, fact.sample, band.nodata_value)
            if value is not None:
                values[fact.name] = round(value, 4)
        out[site_id] = values
    return out


def reclass_values(tool: Tool) -> str:
    """GeoLibre `reclass` rows ("new,from,to_less_than;...") for a tool's zone classes:
    0 below the lowest class, then 1, 2, ... in order."""
    classes = tool.zones.classes
    rows = [f"0,-1e30,{classes[0].min!r}"]
    for index, zone_class in enumerate(classes):
        upper = classes[index + 1].min if index + 1 < len(classes) else 1e30
        rows.append(f"{index + 1},{zone_class.min!r},{upper!r}")
    return ";".join(rows)


def polygonise(wasm: Path, tool: Tool, raster: GDALRaster, core, srid, nodata, label):
    """Zone polygons inside `core`, as (class name, GeoJSON geometry) pairs, in chunks."""
    resolution = raster.scale.x
    size = ZONE_CHUNK_CELLS * resolution
    pieces, peak = [], 0
    xmin, ymin, xmax, ymax = core
    for row in range(math.ceil((ymax - ymin) / size)):
        for column in range(math.ceil((xmax - xmin) / size)):
            chunk = (
                xmin + column * size,
                max(ymin, ymax - (row + 1) * size),
                min(xmax, xmin + (column + 1) * size),
                ymax - row * size,
            )
            cut = dem.warp_bytes(
                raster,
                chunk,
                resolution,
                srid,
                nodata,
                "NearestNeighbour",
                f"{label}-{row}-{column}",
            )
            classes = runtime.run(
                wasm,
                "reclass",
                {
                    "input": "/work/in.tif",
                    "output": "/work/classes.tif",
                    "reclass_values": reclass_values(tool),
                },
                {"in.tif": cut},
            )
            polygons = runtime.run(
                wasm,
                "raster_to_vector_polygons",
                {"input": "/work/classes.tif", "output": "/work/zones.geojson"},
                {"classes.tif": classes.files["classes.tif"]},
            )
            peak = max(peak, classes.peak_memory, polygons.peak_memory)
            for feature in json.loads(polygons.files["zones.geojson"])["features"]:
                index = int(feature["properties"]["VALUE"]) - 1
                if 0 <= index < len(tool.zones.classes):
                    pieces.append((tool.zones.classes[index].name, feature["geometry"]))
    return pieces, peak


def process_tile(task: dict) -> dict:
    """One tool on one tile (worker side)."""
    started = time.perf_counter()
    tool: Tool = task["tool"]
    tile: Tile = task["tile"]
    grid = tool.grid
    dem_tif = dem.tile_bytes(
        Path(task["src"]),
        tile.padded,
        grid.resolution_m,
        task["srid"],
        task["nodata"],
        task["same_grid"],
        f"{tool.id}-{tile.key}",
    )
    output, peak = run_chain(Path(task["wasm"]), tool, dem_tif)
    raster = GDALRaster(output)
    facts = sample_sites(raster, tool, task["sites"]) if tool.facts else {}
    pieces = []
    if tool.zones:
        pieces, zone_peak = polygonise(
            Path(task["wasm"]),
            tool,
            raster,
            tile.core,
            task["srid"],
            task["nodata"],
            f"{tool.id}-{tile.key}",
        )
        peak = max(peak, zone_peak)
    return {
        "tool": tool.id,
        "tile": tile.key,
        "facts": facts,
        "zones": pieces,
        "seconds": time.perf_counter() - started,
        "peak_mb": peak / 2**20,
    }


def process_sites(task: dict) -> dict:
    """The viewshed for a batch of sites (worker side)."""
    started = time.perf_counter()
    tool: Tool = task["tool"]
    resolution = tool.grid.resolution_m
    radius = tool.per_site["radius_m"]
    wasm = Path(task["wasm"])
    out, failed, peak = {}, {}, 0
    for site_id, x, y in task["sites"]:
        bounds = (
            math.floor((x - radius) / resolution) * resolution,
            math.floor((y - radius) / resolution) * resolution,
            math.ceil((x + radius) / resolution) * resolution,
            math.ceil((y + radius) / resolution) * resolution,
        )
        window = dem.tile_bytes(
            Path(task["src"]),
            bounds,
            resolution,
            task["srid"],
            task["nodata"],
            True,
            f"view-{site_id}",
        )
        stations = json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {
                    "type": "name",
                    "properties": {"name": f"urn:ogc:def:crs:EPSG::{task['srid']}"},
                },
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": site_id},
                        "geometry": {"type": "Point", "coordinates": [x, y]},
                    }
                ],
            }
        ).encode()
        try:
            shed = runtime.run(
                wasm,
                "viewshed",
                {
                    "input": "/work/dem.tif",
                    "stations": "/work/stations.geojson",
                    "height": tool.per_site["eye_height_m"],
                    "output": "/work/viewshed.tif",
                },
                {"dem.tif": window, "stations.geojson": stations},
            )
        except runtime.ToolFailed as error:
            # A site off the DEM (nodata under it) has no viewshed; the rest go on.
            failed[site_id] = str(error)
            continue
        raster = GDALRaster(shed.files["viewshed.tif"])
        visible = raster.bands[0].data()
        site_cell = (int((x - bounds[0]) // resolution), int((bounds[3] - y) // resolution))
        area, direction = mappers.view_stats(
            visible, raster.width, raster.height, resolution, site_cell, task["view_cfg"]
        )
        polygons = runtime.run(
            wasm,
            "raster_to_vector_polygons",
            {"input": "/work/viewshed.tif", "output": "/work/visible.geojson"},
            {"viewshed.tif": shed.files["viewshed.tif"]},
        )
        peak = max(peak, shed.peak_memory, polygons.peak_memory)
        geometries = [
            f["geometry"]
            for f in json.loads(polygons.files["visible.geojson"])["features"]
            if int(f["properties"]["VALUE"]) == 1
        ]
        out[site_id] = {"area_km2": area, "direction": direction, "polygons": geometries}
    return {
        "tool": tool.id,
        "tile": task["key"],
        "sites": out,
        "failed": failed,
        "seconds": time.perf_counter() - started,
        "peak_mb": peak / 2**20,
    }


def dispatch(task: tuple[str, dict]) -> dict:
    """Run one ("tile" | "sites", task) pair; the pool's entry point."""
    kind, body = task
    return process_tile(body) if kind == "tile" else process_sites(body)
