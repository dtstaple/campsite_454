"""Spatial questions about a user's planning data, for the GPX exports."""

from django.contrib.gis.geos import LineString
from django.contrib.gis.measure import D

from api.gpx import Waypoint as GpxWaypoint

from .models import Waypoint

#: Garmin-style symbol names, which most GPS apps understand; `type` keeps the exact kind.
GPX_SYMBOLS = {
    Waypoint.Kind.WATER: "Drinking Water",
    Waypoint.Kind.CAMP: "Campground",
    Waypoint.Kind.BAILOUT: "Trail Head",
    Waypoint.Kind.CUSTOM: "Flag, Blue",
}


def waypoints_near(user, line_m: LineString, within_m: float):
    """The user's waypoints within `within_m` metres of a METRIC_SRID line, in the order
    they were made. Indexed: ST_DWithin on geom_m uses waypoint_geom_m_gist."""
    if not user or not user.is_authenticated:
        return Waypoint.objects.none()
    return Waypoint.objects.filter(user=user, geom_m__dwithin=(line_m, D(m=within_m)))


def as_gpx(waypoints) -> list[GpxWaypoint]:
    return [
        GpxWaypoint(
            lon=w.geom.x,
            lat=w.geom.y,
            name=w.name,
            desc=w.note or None,
            sym=GPX_SYMBOLS.get(w.kind),
            type=f"waypoint:{w.kind}",
        )
        for w in waypoints
    ]
