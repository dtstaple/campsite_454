"""
Where the graph build's edge elevations come from (TM05-149).

The terrain pipeline (`make terrain`, docs/terrain-analysis.md) keeps the region's 3DEP
1/3 arc-second source tiles on disk, with a GDAL VRT over them:

    <cache_dir>/3dep-13/USGS_13_<tile>.tif, signature.json
    <cache_dir>/mosaic/<region>-<digest>.vrt

When every tile for the region is there, the build samples that mosaic locally (bilinear,
like 3DEP's getSamples) instead of asking the ImageServer, which was nearly all of a first
build's time. When it isn't, the build asks 3DEP's getSamples exactly as before. Points
the mosaic has no data for are asked of 3DEP too, so a gap never becomes a flat edge.

Nothing is downloaded here and nothing raster is stored: the build reads tiles the terrain
pipeline already fetched, and keeps only the samples on each edge, as before.
"""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from django.contrib.gis.gdal import CoordTransform, GDALRaster, SpatialReference

from analysis.analyses.elevation import fetch_elevations
from terrain import dem
from terrain.runtime import cache_dir

#: build_region(elevation=...): "auto" uses the cached mosaic when there is one.
MODES = ("auto", "cache", "3dep")


def cached_source(region: str, bbox) -> dem.Source | None:
    """The terrain pipeline's downloaded source tiles for `bbox`, when all are on disk."""
    directory = cache_dir() / "3dep-13"
    signature_file = directory / "signature.json"
    if not signature_file.exists():
        return None
    known = json.loads(signature_file.read_text())
    names = dem.source_tiles(bbox)
    if not all(n in known and (directory / f"USGS_13_{n}.tif").exists() for n in names):
        return None
    return dem.Source(region, names, directory, {n: known[n] for n in names})


def _flat(values) -> list[float]:
    """GDALBand.data() is a numpy array when numpy is installed, else a flat list."""
    return values.ravel().tolist() if hasattr(values, "ravel") else list(values)


class MosaicSampler:
    """A `fetch(points) -> (values, source)` over a local DEM, for routing.build.climb.

    Values are bilinear between the four nearest cell centres. A cell with no data drops
    out of the weights; a point with no data around it at all is asked of `fallback`.
    Each thread opens its own raster, since a GDAL dataset is not safe to share.
    """

    def __init__(self, path: Path, fallback: Callable = fetch_elevations, label: str = ""):
        self.path = Path(path)
        self.fallback = fallback
        self.label = label or f"3DEP 1/3 arc-second mosaic {self.path.name}"
        self._local = threading.local()

    def _open(self):
        if not hasattr(self._local, "raster"):
            raster = GDALRaster(str(self.path))
            band = raster.bands[0]
            self._local.raster = raster
            self._local.band = band
            self._local.transform = CoordTransform(SpatialReference(4326), raster.srs)
        return self._local.raster, self._local.band, self._local.transform

    def sample(self, x: float, y: float) -> float | None:
        """The elevation at (x, y) in the raster's CRS, or None."""
        raster, band, _ = self._open()
        nodata = band.nodata_value
        # Pixel coordinates measured from the first cell's centre.
        px = (x - raster.origin.x) / raster.scale.x - 0.5
        py = (y - raster.origin.y) / raster.scale.y - 0.5
        if not (-0.5 <= px <= raster.width - 0.5 and -0.5 <= py <= raster.height - 0.5):
            return None
        # The 2x2 window of cell centres around the point (a DEM is at least 2x2 cells).
        i0 = min(max(math.floor(px), 0), raster.width - 2)
        j0 = min(max(math.floor(py), 0), raster.height - 2)
        fx, fy = min(max(px - i0, 0.0), 1.0), min(max(py - j0, 0.0), 1.0)
        cells = _flat(band.data(offset=(i0, j0), size=(2, 2)))
        weights = ((1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy)
        total = weight = 0.0
        for z, wk in zip(cells, weights, strict=True):
            if wk <= 0 or z == nodata or math.isnan(z):
                continue
            total += wk * z
            weight += wk
        return total / weight if weight > 0 else None

    def __call__(self, points) -> tuple[list[float | None], dict]:
        _, _, transform = self._open()
        values: list[float | None] = []
        for p in points:
            q = p.transform(transform, clone=True)
            values.append(self.sample(q.x, q.y))
        datasets = {self.label}
        missing = [i for i, v in enumerate(values) if v is None]
        if missing and self.fallback is not None:
            filled, source = self.fallback([points[i] for i in missing])
            for i, value in zip(missing, filled, strict=True):
                values[i] = value
            datasets.update(source.get("datasets", []))
        return values, {"datasets": sorted(datasets), "fallback_points": len(missing)}


@dataclass
class Choice:
    fetch: Callable
    provenance: dict


def choose(region: str, bbox, mode: str = "auto") -> Choice:
    """The elevation source for a build: the cached mosaic when `mode` allows it and the
    tiles are there, otherwise 3DEP's getSamples. `mode="cache"` insists on the mosaic."""
    if mode not in MODES:
        raise ValueError(f"Unknown elevation source {mode!r}; use one of {', '.join(MODES)}.")
    source = cached_source(region, bbox) if mode != "3dep" else None
    if source is None:
        if mode == "cache":
            raise FileNotFoundError(
                f"No cached 3DEP tiles for {region} in {cache_dir() / '3dep-13'}; "
                f"run `make terrain REGION={region}` first, or use --elevation auto."
            )
        return Choice(fetch_elevations, {"elevation_source": "3dep-getsamples"})
    vrt = dem.build_vrt(source)
    return Choice(
        MosaicSampler(vrt),
        {
            "elevation_source": "dem-cache",
            "mosaic": vrt.name,
            "mosaic_digest": source.digest,
            "tiles": sorted(source.names),
        },
    )
