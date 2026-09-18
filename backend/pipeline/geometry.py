"""
Geometry helpers shared by adapters.

Lives outside any one adapter because more than one source needs it: OSM does not tag
trail length, and NHD flowlines will want the same calculation. Copy-pasting it per
adapter is exactly what the framework exists to prevent.
"""

import math

# IUGG mean Earth radius. Using a sphere rather than the WGS84 ellipsoid is a deliberate
# accuracy-for-simplicity trade -- see geodesic_length_m.
EARTH_RADIUS_M = 6371008.8


def geodesic_length_m(coordinates) -> float:
    """Length in metres of a (lon, lat) path in EPSG:4326.

    Our geometry columns store degrees, so the plain `.length` of a GEOS geometry is a
    meaningless number in degrees of arc -- and an inconsistent one, since a degree of
    longitude is about 79 km at Adirondack latitude against 111 km for a degree of
    latitude. This walks consecutive vertices and sums great-circle distances instead.

    Accuracy: measured against PostGIS `ST_Length(geography)`, which uses the WGS84
    ellipsoid, across a sample of real OSM trails in the Adirondacks -- worst case 0.25%,
    typically 0.13%. On a 15 km trail that is roughly 18 m. Comfortably inside what a
    campsite score needs, and it avoids adding pyproj as a dependency for one function.

    If sub-metre length ever matters, the upgrade path is PostGIS: cast the stored
    geometry to geography and let the database compute it.
    """
    total = 0.0
    previous = None

    for longitude, latitude in coordinates:
        if previous is not None:
            total += _haversine_m(previous, (longitude, latitude))
        previous = (longitude, latitude)

    return total


def _haversine_m(start, end) -> float:
    lon1, lat1 = start
    lon2, lat2 = end

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
