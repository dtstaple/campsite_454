"""
From tool rasters to campsite facts (TM05-141). Pure: lists of numbers in, values out.

Sampling reads a small square of cells around the site, not the single cell under it,
because a campsite point is placed by hand and often sits on a stream line or trail
edge (docs/terrain-analysis.md, "Limits"). The classes turn those numbers into the
words the app shows, using thresholds from tools.yml `classify`.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

DIRECTIONS = (
    "north",
    "northeast",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
)


def _valid(values: Sequence[float], nodata: float | None) -> list[float]:
    return [
        v
        for v in values
        if v is not None and not math.isnan(v) and (nodata is None or abs(v - nodata) > 1e-6)
    ]


def sample(values: Sequence[float], method: str, nodata: float | None) -> float | None:
    """One value from the cells around a site; None when every cell is nodata."""
    if method == "circular_mean":
        # Aspect: GeoLibre writes -1 on flat cells, which have no direction.
        angles = [v for v in _valid(values, nodata) if v >= 0]
        if not angles:
            return None
        x = sum(math.sin(math.radians(a)) for a in angles)
        y = sum(math.cos(math.radians(a)) for a in angles)
        if math.hypot(x, y) < 1e-9:
            return None
        # Rounded first, so a mean a hair west of north is 0, not 360.
        return round(math.degrees(math.atan2(x, y)), 6) % 360
    valid = _valid(values, nodata)
    if not valid:
        return None
    if method == "median":
        return statistics.median(valid)
    if method == "max":
        return max(valid)
    if method == "min":
        return min(valid)
    raise ValueError(f"unknown sample method {method!r}")


def sector(azimuth_deg: float) -> str:
    """The 8-point compass name of an azimuth (clockwise from north)."""
    return DIRECTIONS[int(((azimuth_deg % 360) + 22.5) // 45) % 8]


# --- classes ------------------------------------------------------------------------


def pooling(values: dict, cfg: dict) -> tuple[str, str]:
    """Water pooling risk and its reason, from the wetness index (low ground that water
    drains into) and sink depth (a hollow that can hold it).

    A hollow alone is at most medium. Many deep "sinks" under Adirondack campsites are
    DEM artefacts: a road embankment over a culvert, or a pond the elevation model
    flattened. A hollow becomes high only when water also drains into it
    (`sink_high_needs_twi`). Measured on the region's 742 sites, this gives 7% high.
    """
    depth, twi = values.get("sink_depth_m"), values.get("twi")
    if depth is None and twi is None:
        return "", ""
    sink, wet = cfg["sink_depth_m"], cfg["twi"]
    if twi is not None and twi >= wet["high"]:
        return "high", f"Low ground that water drains into from upslope (wetness index {twi:.1f})."
    hollow = depth is not None and depth >= sink["medium"]
    if hollow and depth >= sink["high"] and twi is not None and twi >= cfg["sink_high_needs_twi"]:
        return (
            "high",
            f"Sits in a hollow about {depth:.1f} m deep that water drains into "
            f"(wetness index {twi:.1f}).",
        )
    if hollow:
        return "medium", f"Sits in a hollow about {depth:.1f} m deep, where rain can collect."
    if twi is not None and twi >= wet["medium"]:
        return "medium", f"Some water drains toward here (wetness index {twi:.1f})."
    if twi is not None:
        return "low", f"Water drains away from here (wetness index {twi:.1f})."
    return "low", "No hollow here for water to collect in."


def sun(values: dict, cfg: dict) -> tuple[str, str]:
    """(facing, sun) from aspect and slope, e.g. ("east", "morning sun")."""
    slope, aspect = values.get("slope_deg"), values.get("aspect_deg")
    if slope is not None and slope < cfg["flat_below_deg"]:
        return "flat", "sun all day where trees allow"
    if aspect is None:
        return "", ""
    facing = sector(aspect)
    for entry in cfg["sectors"]:
        if entry["facing"] == facing:
            return facing, entry["sun"]
    raise ValueError(f"classify.sun.sectors has no entry for {facing}")


def shelter(values: dict, cfg: dict) -> tuple[str, str]:
    """Sheltered, moderate or exposed, from the site's height against its surroundings."""
    dev = values.get("dev")
    if dev is None:
        return "", ""
    if dev >= cfg["exposed_from"]:
        return "exposed", "Stands well above the ground around it, open to wind."
    if dev < cfg["sheltered_below"]:
        return "sheltered", "Lies lower than the ground around it, out of the wind."
    return "moderate", "About level with the ground around it."


# --- viewshed -----------------------------------------------------------------------


def view_stats(
    visible: Sequence[float],
    width: int,
    height: int,
    resolution: float,
    site: tuple[int, int],
    cfg: dict,
) -> tuple[float, str]:
    """(visible area km², main direction) from a 0/1 viewshed raster, row-major.

    The direction is the compass sector holding the most visible ground beyond
    `near_m`, which is always visible and says nothing about the view. It is named
    only when it holds at least `direction_share` of that ground; otherwise the view
    is "all around".
    """
    column, row = site
    near = cfg["near_m"] / resolution
    shares = [0] * 8
    total = 0
    for index, value in enumerate(visible):
        if value is None or value < 0.5 or value > 1.5:
            continue
        total += 1
        dx = index % width - column
        dy = row - index // width  # rows grow southward
        if math.hypot(dx, dy) <= near:
            continue
        shares[DIRECTIONS.index(sector(math.degrees(math.atan2(dx, dy))))] += 1
    area_km2 = total * resolution * resolution / 1e6
    far = sum(shares)
    if far == 0:
        return area_km2, ""
    best = max(range(8), key=lambda i: shares[i])
    if shares[best] / far < cfg["direction_share"]:
        return area_km2, "all around"
    return area_km2, DIRECTIONS[best]
