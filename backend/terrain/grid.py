"""
Cutting a region into tiles with overlap (TM05-141). Pure: numbers in, tiles out.

The tile **cores** partition the region's grid exactly: every cell, and every campsite,
belongs to one core. Each tile is processed on its core plus `overlap` cells on every
side, then only the core is kept.

A tool whose neighbourhood fits inside the overlap therefore gives the same value at
every core cell as it would on the untiled raster. Cut-off neighbourhoods exist only
in the discarded margin, so there are no seams. `tests/test_terrain.py` checks this
with a neighbourhood operation.

Coordinates are EPSG:5070 metres. Grids are aligned to multiples of the resolution
(GDAL's -tap), so tiles at one resolution always line up with each other and with the
region mosaic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Bounds = tuple[float, float, float, float]  # xmin, ymin, xmax, ymax


@dataclass(frozen=True)
class Tile:
    ix: int
    iy: int
    #: The cells this tile answers for.
    core: Bounds
    #: The cells it is computed on: the core plus the overlap, clipped to the region.
    padded: Bounds

    @property
    def key(self) -> str:
        return f"{self.ix}-{self.iy}"


def align(bounds: Bounds, resolution: float) -> Bounds:
    """Snap outward to multiples of the resolution."""
    xmin, ymin, xmax, ymax = bounds
    return (
        math.floor(xmin / resolution) * resolution,
        math.floor(ymin / resolution) * resolution,
        math.ceil(xmax / resolution) * resolution,
        math.ceil(ymax / resolution) * resolution,
    )


def cells(bounds: Bounds, resolution: float) -> tuple[int, int]:
    """(columns, rows) of an aligned extent."""
    xmin, ymin, xmax, ymax = bounds
    return round((xmax - xmin) / resolution), round((ymax - ymin) / resolution)


def layout(
    region: Bounds, resolution: float, tile_cells: int | None, overlap_m: float
) -> list[Tile]:
    """Tiles covering `region`, row by row from the north-west. With no `tile_cells`,
    one tile is the whole region."""
    region = align(region, resolution)
    xmin, ymin, xmax, ymax = region
    if tile_cells is None:
        return [Tile(0, 0, region, region)]
    columns, rows = cells(region, resolution)
    size = tile_cells * resolution
    pad = math.ceil(overlap_m / resolution) * resolution
    tiles = []
    for iy in range(math.ceil(rows / tile_cells)):
        top = ymax - iy * size
        bottom = max(ymin, top - size)
        for ix in range(math.ceil(columns / tile_cells)):
            left = xmin + ix * size
            right = min(xmax, left + size)
            core = (left, bottom, right, top)
            padded = (
                max(xmin, left - pad),
                max(ymin, bottom - pad),
                min(xmax, right + pad),
                min(ymax, top + pad),
            )
            tiles.append(Tile(ix, iy, core, padded))
    return tiles


def contains(core: Bounds, x: float, y: float) -> bool:
    """Whether a point is in a core. Half-open (west and south edges in, east and north
    out), so a point on a shared edge belongs to exactly one tile. The region is aligned
    outward from the regions.yml bbox, so no campsite in the bbox sits on its outer edge."""
    xmin, ymin, xmax, ymax = core
    return xmin <= x < xmax and ymin <= y < ymax


def window(padded: Bounds, core: Bounds, resolution: float) -> tuple[int, int, int, int]:
    """The core's (column offset, row offset, columns, rows) inside the padded raster,
    whose origin is its north-west corner."""
    column = round((core[0] - padded[0]) / resolution)
    row = round((padded[3] - core[3]) / resolution)
    width, height = cells(core, resolution)
    return column, row, width, height
