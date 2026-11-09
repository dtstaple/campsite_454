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


def cold_air(values: dict, cfg: dict) -> tuple[str, str]:
    """Cold-air pooling (TM05-147): low, medium or high, from the site's elevation
    percentile, the share of the ground within about 1 km that lies lower than it.

    On clear, calm nights air chilled by the ground drains downhill and settles in the
    lowest ground around, so the lower a site sits among its surroundings, the colder,
    frostier and damper with dew its nights. The zones (tools.yml `cold_air`) use the same
    thresholds, so the map and the panel agree.
    """
    rank = values.get("elev_percentile")
    if rank is None:
        return "", ""
    higher = round(100 - rank)
    if rank < cfg["high_below"]:
        return (
            "high",
            f"In the lowest ground around: higher than only {round(rank)}% of the land "
            "within about 1 km, where cold air settles on clear, calm nights.",
        )
    if rank < cfg["medium_below"]:
        return (
            "medium",
            f"Low-lying: {higher}% of the land within about 1 km is higher, so some cold "
            "air drains down to here on calm nights.",
        )
    return "low", f"Cold air drains away: {round(rank)}% of the land within about 1 km is lower."


def wind(values: dict, cfg: dict, from_deg: float | None) -> tuple[str, str]:
    """Exposure to the prevailing wind (TM05-148): sheltered, moderate or exposed, from
    how far upwind the ground first rises against a wind from `from_deg`.

    `wind_fetch_m` is fetch_analysis's distance to that ground. Negative means nothing
    rose before the DEM ended, after searching that many metres: open ground when the
    search reached `exposed_from_m`, and unknown when the region's edge cut it shorter.
    """
    fetch = values.get("wind_fetch_m")
    if fetch is None or from_deg is None:
        return "", ""
    side = sector(from_deg)
    within, exposed = cfg["sheltered_within_m"], cfg["exposed_from_m"]
    if fetch < 0:
        if -fetch < exposed:
            return "", ""
        return (
            "exposed",
            f"Open to a {side} wind: no ground rises against it for at least "
            f"{-fetch / 1000:.1f} km upwind.",
        )
    if fetch < within:
        return (
            "sheltered",
            f"Ground rises against a {side} wind about {round(fetch, -1):.0f} m upwind, "
            "breaking it before it reaches here.",
        )
    if fetch < exposed:
        return (
            "moderate",
            f"Partly open to a {side} wind: the nearest ground rising against it is about "
            f"{round(fetch, -1):.0f} m upwind.",
        )
    return (
        "exposed",
        f"Open to a {side} wind: about {fetch / 1000:.1f} km of open ground upwind.",
    )


#: The sun's centre is this far below a flat horizon at sunrise and sunset (refraction
#: and the sun's radius), the usual definition of daylight.
SUNRISE_ALTITUDE_DEG = -0.833


def day_length_h(latitude_deg: float, day_of_year: int) -> float:
    """Hours from sunrise to sunset over a flat horizon, from the sun's declination
    (Cooper's approximation; within a few minutes, which is all an estimate needs)."""
    declination = math.radians(23.44) * math.sin(2 * math.pi * (284 + day_of_year) / 365)
    latitude = math.radians(latitude_deg)
    cos_hour = (
        math.sin(math.radians(SUNRISE_ALTITUDE_DEG)) - math.sin(latitude) * math.sin(declination)
    ) / (math.cos(latitude) * math.cos(declination))
    # Beyond the polar circles the sun can stay up (or down) all day.
    hour_angle = math.degrees(math.acos(max(-1.0, min(1.0, cos_hour))))
    return 2 * hour_angle / 15


def season_daylight_h(latitude_deg: float, start_day: int, end_day: int) -> float:
    """The mean day length over days `start_day` to `end_day` inclusive."""
    days = range(start_day, end_day + 1)
    return sum(day_length_h(latitude_deg, day) for day in days) / len(days)


def clock(time_text: str) -> str:
    """ "10:00:00" as the panel says it, "10 am"; "13:30:00" is "1:30 pm"."""
    hours, minutes = (int(part) for part in time_text.split(":")[:2])
    suffix = "am" if hours < 12 else "pm"
    hours = hours % 12 or 12
    return f"{hours} {suffix}" if minutes == 0 else f"{hours}:{minutes:02d} {suffix}"


def sun_hours(
    values: dict, cfg: dict, latitude_deg: float | None
) -> tuple[float | None, str, str, bool | None, str]:
    """Direct sun (TM05-162): (hours, level, reason, morning sun, morning reason).

    `sun_share` is time_in_daylight's share of the season's daytime the site is in direct
    sun, not in the shadow of terrain. Hours are that share of the mean day length over
    the season at the site's latitude: about 15 h in an Adirondack summer, so a share of
    0.8 is about 12 h. The level is `full`, `partial` or `low`. Morning sun is whether
    the site is lit for at least `morning_from_share` of sunrise to `morning_until`.
    Either half is unknown on its own when its value is missing.
    """
    share, morning_share = values.get("sun_share"), values.get("morning_sun_share")
    hours, level, reason = None, "", ""
    season, until = cfg["season"], clock(cfg["morning_until"])
    if share is not None and latitude_deg is not None:
        daylight = season_daylight_h(latitude_deg, cfg["start_day"], cfg["end_day"])
        hours = round(max(0.0, min(1.0, share)) * daylight, 1)
        rounded, day = round(hours), round(daylight)
        if hours >= cfg["full_from_h"]:
            level = "full"
            reason = (
                f"About {rounded} h of direct sun on a day in {season}, out of about {day} h "
                "of daylight."
            )
        elif hours >= cfg["partial_from_h"]:
            level = "partial"
            reason = (
                f"About {rounded} h of direct sun on a day in {season}: the terrain shades it "
                f"for about {day - rounded} of the {day} h of daylight."
            )
        else:
            level = "low"
            reason = (
                f"Only about {rounded} h of direct sun on a day in {season}: the terrain "
                f"shades it for most of the {day} h of daylight."
            )
    morning, morning_reason = None, ""
    if morning_share is not None:
        morning = morning_share >= cfg["morning_from_share"]
        morning_reason = (
            f"In direct sun for most of the time from sunrise to {until}."
            if morning
            else f"Higher ground shades it for most of the time from sunrise to {until}."
        )
    return hours, level, reason, morning, morning_reason


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
