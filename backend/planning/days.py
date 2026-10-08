"""
Each day of an overnight plan (TM05-81): distance, gain and loss between stops.

Pure -- lists in, numbers out -- so it is tested without a database or 3DEP.

The numbers come from the route's stored elevation profile (analysis/analyses/elevation.py),
measured the same way as the whole route's: the profile is smoothed once over its full
length with the route's own window, then each day's slice is counted with the same
3 m threshold. Smoothing once rather than per day means a day boundary does not change
the elevations on either side of it. The days' gains add up to the route's gain to within
a threshold or so per stop: the threshold restarts at each stop, which is what a hiker
counting their own day would do.
"""

import bisect

from analysis.analyses.elevation import gain_loss, smooth


def value_at(distances: list[float], values: list[float], at: float) -> float:
    """Linear interpolation in the profile, clamped to its ends."""
    if at <= distances[0]:
        return values[0]
    if at >= distances[-1]:
        return values[-1]
    i = bisect.bisect_right(distances, at)
    d0, d1 = distances[i - 1], distances[i]
    v0, v1 = values[i - 1], values[i]
    return v0 if d1 == d0 else v0 + (v1 - v0) * (at - d0) / (d1 - d0)


def smoothed_profile(elevations: list[float], params: dict) -> list[float]:
    window = max(1, round(params["smoothing_window_m"] / params["spacing_m"])) | 1  # odd
    return smooth(elevations, window)


def day_stats(
    cuts: list[float], distances: list[float] | None, smoothed: list[float] | None, params
) -> list[dict]:
    """One entry per day between consecutive `cuts` (metres along the route: 0, each stop,
    the route's length). Gain and loss are None when there is no profile."""
    days = []
    for start, end in zip(cuts, cuts[1:], strict=False):
        day = {
            "start_m": round(start, 1),
            "end_m": round(end, 1),
            "distance_m": round(end - start, 1),
            "gain_m": None,
            "loss_m": None,
        }
        if distances and smoothed:
            inside = [smoothed[i] for i, d in enumerate(distances) if start < d < end]
            series = [value_at(distances, smoothed, start), *inside]
            series.append(value_at(distances, smoothed, end))
            gain, loss = gain_loss(series, params["threshold_m"])
            day["gain_m"], day["loss_m"] = round(gain, 1), round(loss, 1)
        days.append(day)
    return days
