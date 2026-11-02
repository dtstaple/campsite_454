"""
What the terrain lets you see from any point on the map (TM05-151).

The same GeoLibre `viewshed` the terrain pipeline runs for every campsite (TM05-141,
terrain/worker.py `viewshed_at`), with the same eye height, grid and view classes, but for
a point someone long-presses on the map. Computed on request, on this server, from the
region's elevation mosaic that `make terrain` leaves in the terrain cache.

Cached through the analysis cache (TM05-44) per rounded location and radius:

- the point is snapped to a GRID_DEGREES cell, about 50 m by 40 m here, so presses a few
  metres apart share one answer. 50 m is under two cells of the 30 m grid the viewshed
  runs on, so the snapped observer stands on practically the same ground.
- the radius is rounded to RADIUS_STEP_M and clamped to the pipeline's own radius.

Terrain does not change, so answers keep for a year. Only the outline and the numbers are
kept; the rasters exist only for the call (CLAUDE.md, "store derived results").

Bare earth: 3DEP has no trees or buildings, so this is what the ground alone would let you
see. The payload carries the same caveat as a campsite's viewshed (terrain/payload.py).
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry, Point

from analysis.base import Analysis, AnalysisError, Computed
from pipeline.regions import load_regions
from terrain import registry as terrain_registry
from terrain import runtime, worker
from terrain.models import TerrainRun
from terrain.pipeline import view_outline
from terrain.runtime import cache_dir, runtime_path

GRID_DEGREES = 0.0005
RADIUS_STEP_M = 1000
MIN_RADIUS_M = 1000


class OutsideCoverage(AnalysisError):
    """The point is in no region from regions.yml."""


class TerrainUnavailable(AnalysisError):
    """The region's elevation mosaic or the GeoLibre runtime isn't on this server."""


def region_at(lon: float, lat: float) -> str | None:
    for name, aoi in load_regions().items():
        west, south, east, north = aoi.bbox
        if west <= lon <= east and south <= lat <= north:
            return name
    return None


def viewshed_tool():
    loaded = terrain_registry.load()
    return loaded, loaded.tools["viewshed"]


def max_radius_m() -> int:
    _, tool = viewshed_tool()
    return int(tool.per_site["radius_m"])


def inputs(region: str, registry) -> tuple[Path, Path, bool, dict]:
    """(runtime, DEM, whether the DEM is already on the viewshed grid, provenance) from
    the terrain cache, without downloading anything: a request never pulls 2.6 GB of 3DEP
    or the 24 MB runtime. The newest finished `make terrain` run says which DEM digest."""
    run = TerrainRun.objects.filter(region=region, finished_at__isnull=False).first()
    if run is None:
        raise TerrainUnavailable(f"The terrain model hasn't been built for {region} yet.")
    # runtime_path() downloads a missing runtime; only call it when one is already here.
    local = cache_dir() / "geolibre" / Path(registry.runtime["url"]).name
    if not os.environ.get("GEOLIBRE_WASM") and not local.exists():
        raise TerrainUnavailable("The terrain tools aren't installed on this server.")
    try:
        wasm = runtime_path(registry.runtime)
    except (FileNotFoundError, RuntimeError) as error:
        raise TerrainUnavailable("The terrain tools on this server don't check out.") from error

    resolution = int(viewshed_tool()[1].grid.resolution_m)
    mosaic = cache_dir() / "mosaic" / f"{region}-{resolution}m-{run.dem_digest}.tif"
    vrt = cache_dir() / "mosaic" / f"{region}-{run.dem_digest}.vrt"
    if mosaic.exists():
        dem_path, same_grid = mosaic, True
    elif vrt.exists():
        dem_path, same_grid = vrt, False
    else:
        raise TerrainUnavailable(f"The elevation model for {region} isn't on this server.")
    provenance = {
        "source": registry.dem["name"],
        "dem_digest": run.dem_digest,
        "terrain_run": run.id,
        "runtime": registry.runtime["version"],
    }
    return wasm, dem_path, same_grid, provenance


class PointViewshed(Analysis):
    name = "point_viewshed"
    version = "1"
    ttl = timedelta(days=365)
    grid_degrees = GRID_DEGREES

    def canonical_params(self, params: dict) -> dict:
        top = max_radius_m()
        radius = float(params.get("radius_m", top))
        radius = round(radius / RADIUS_STEP_M) * RADIUS_STEP_M
        return {"radius_m": int(min(top, max(MIN_RADIUS_M, radius)))}

    def compute(self, geom: GEOSGeometry, window, params) -> Computed:
        lon, lat = geom.x, geom.y
        region = region_at(lon, lat)
        if region is None:
            raise OutsideCoverage("That point is outside the areas CampSite covers.")
        registry, tool = viewshed_tool()
        wasm, dem_path, same_grid, provenance = inputs(region, registry)
        srid, nodata = int(registry.dem["srid"]), float(registry.dem["nodata"])
        observer = Point(lon, lat, srid=4326).transform(srid, clone=True)
        try:
            view, _ = worker.viewshed_at(
                wasm,
                dem_path,
                srid,
                nodata,
                observer.x,
                observer.y,
                radius_m=params["radius_m"],
                resolution_m=tool.grid.resolution_m,
                eye_height_m=tool.per_site["eye_height_m"],
                view_cfg=registry.classify["view"],
                label=f"point-{lon:.4f}-{lat:.4f}",
                same_grid=same_grid,
            )
        except runtime.ToolFailed as error:
            raise AnalysisError("There's no elevation data under that point.") from error
        shape = view_outline(view["polygons"])
        return Computed(
            value={
                "region": region,
                "observer": {"lon": round(lon, 6), "lat": round(lat, 6)},
                "radius_m": params["radius_m"],
                "eye_height_m": tool.per_site["eye_height_m"],
                "resolution_m": tool.grid.resolution_m,
                "area_km2": round(view["area_km2"], 3),
                "direction": view["direction"] or None,
                "geometry": json.loads(shape.json) if shape else None,
            },
            provenance=provenance,
        )
