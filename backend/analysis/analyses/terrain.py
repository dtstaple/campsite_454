"""
Elevation and slope at a point (TM05-64), from the same USGS 3DEP sampler as route
profiles (TM05-59, analysis/analyses/elevation.py).

Slope comes from a 3x3 stencil of elevations around the point, `stencil_m` apart (10 m by
default), using Horn's method -- the weighted finite difference GIS packages use for
slope rasters:

    dz/dx = ((z3 + 2 z6 + z9) - (z1 + 2 z4 + z7)) / (8 h)        z1 z2 z3   north
    dz/dy = ((z1 + 2 z2 + z3) - (z7 + 2 z8 + z9)) / (8 h)        z4 z5 z6
    slope = atan(sqrt(dz/dx^2 + dz/dy^2))                         z7 z8 z9   south

10 m is campsite scale: a tent pad and the ground around it. Smaller would read rocks
and roots in 1 m LiDAR as slope; larger would blend in the hillside the site was cut into.

Nine points per site batch well: 3DEP takes 400 points per request, so ~44 sites per
request, and run_many() asks only for the sites not already cached. Terrain does not
change, so answers keep for a year.
"""

from __future__ import annotations

import math
from datetime import timedelta

from django.contrib.gis.geos import GEOSGeometry, MultiPoint, Point

from analysis.analyses import elevation
from analysis.base import Analysis, AnalysisError, Computed
from geodata.models import METRIC_SRID

DEFAULT_STENCIL_M = 10.0
METHOD = "horn-3x3"

# Row-major from the north-west corner, matching z1..z9 in the module docstring.
OFFSETS = [(dx, dy) for dy in (1, 0, -1) for dx in (-1, 0, 1)]


def stencil_points(sites: list[Point], spacing_m: float) -> list[Point]:
    """Nine WGS84 points per site, reprojected in two batched calls (one each way)."""
    projected = MultiPoint([Point(p.x, p.y) for p in sites], srid=4326)
    projected.transform(METRIC_SRID)
    grid = MultiPoint(
        [
            Point(c.x + dx * spacing_m, c.y + dy * spacing_m)
            for c in projected
            for dx, dy in OFFSETS
        ],
        srid=METRIC_SRID,
    )
    grid.transform(4326)
    return [Point(p.x, p.y, srid=4326) for p in grid]


def horn_slope(z: list[float], spacing_m: float) -> tuple[float, float]:
    """Slope in (degrees, percent) from nine elevations in OFFSETS order."""
    z1, z2, z3, z4, _, z6, z7, z8, z9 = z
    dzdx = ((z3 + 2 * z6 + z9) - (z1 + 2 * z4 + z7)) / (8 * spacing_m)
    dzdy = ((z1 + 2 * z2 + z3) - (z7 + 2 * z8 + z9)) / (8 * spacing_m)
    rise = math.hypot(dzdx, dzdy)
    return math.degrees(math.atan(rise)), rise * 100


class SiteTerrain(Analysis):
    name = "site_terrain"
    version = "1"
    ttl = timedelta(days=365)
    grid_degrees = None

    def canonical_params(self, params: dict) -> dict:
        return {"stencil_m": float(params.get("stencil_m", DEFAULT_STENCIL_M))}

    def compute(self, geom: GEOSGeometry, window, params) -> Computed:
        result = self.compute_many([geom], window, params)[0]
        if isinstance(result, AnalysisError):
            raise result
        return result

    def compute_many(self, geoms, window, params):
        spacing = float(params.get("stencil_m", DEFAULT_STENCIL_M))
        sites = [Point(g.x, g.y, srid=4326) for g in geoms]
        points = stencil_points(sites, spacing)
        values, source = elevation.fetch_elevations(points)

        results: list[Computed | AnalysisError] = []
        for index in range(len(sites)):
            z = values[index * 9 : index * 9 + 9]
            centre = z[4]
            if centre is None:
                results.append(AnalysisError("3DEP has no elevation at this point"))
                continue
            # A missing neighbour (edge of coverage) borrows the centre value: it flattens
            # that side of the stencil slightly rather than discarding the site.
            filled = [centre if value is None else value for value in z]
            degrees, percent = horn_slope(filled, spacing)
            results.append(
                Computed(
                    {
                        "elevation_m": round(centre, 1),
                        "slope_deg": round(degrees, 2),
                        "slope_pct": round(percent, 1),
                        "stencil_m": spacing,
                        "method": METHOD,
                    },
                    {
                        "source": "usgs-3dep",
                        "url": elevation.THREEDEP_URL,
                        "missing_neighbours": sum(1 for value in z if value is None),
                        **source,
                    },
                )
            )
        return results
