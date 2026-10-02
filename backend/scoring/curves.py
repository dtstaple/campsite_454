"""
The distance curves. Pure functions, so each can be tested and plotted on its own.

Closest is not best. Leave No Trace asks for camps about 200 ft (~60 m) from water and out
of sight of trails, so both curves *peak* at an ideal distance and fall away on both
sides: rising linearly from `at_zero` on the bank to 100 at the ideal, then halving every
`half_distance_m` beyond it.
"""

from __future__ import annotations


def peak_curve(distance_m: float, ideal_m: float, at_zero: float, half_distance_m: float) -> float:
    """Sub-score 0-100 for a distance, peaking at `ideal_m`.

    >>> peak_curve(60, ideal_m=60, at_zero=35, half_distance_m=400)
    100.0
    >>> peak_curve(0, ideal_m=60, at_zero=35, half_distance_m=400)
    35.0
    >>> peak_curve(460, ideal_m=60, at_zero=35, half_distance_m=400)
    50.0
    """
    if distance_m < 0:
        raise ValueError("distance cannot be negative")
    if distance_m <= ideal_m:
        if ideal_m == 0:
            return 100.0
        return at_zero + (100.0 - at_zero) * (distance_m / ideal_m)
    return 100.0 * 0.5 ** ((distance_m - ideal_m) / half_distance_m)
