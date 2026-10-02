"""
Metre-correct, index-backed distance queries (TM05-42).

Every distance in the project should come through here. The rule it encodes: measure on
`geom_m` (EPSG:5070, metres, GiST-indexed), never on `geom` (EPSG:4326, degrees).

Two query shapes cover what scoring needs:

- nearest(): the closest feature and how far it is. Ordered by the KNN operator `<->`
  on `geom_m`, which is what lets PostgreSQL walk the GiST index outward from the point
  instead of computing a distance to every row. Ordering by ST_Distance looks equivalent
  and is not -- it cannot use the index and degrades to a sequential scan.
- within(): every feature inside a radius in metres, via ST_DWithin on `geom_m`, which
  is also index-assisted.

Why a projected column rather than a geography index is measured and written up in
docs/architecture.md.
"""

from __future__ import annotations

from django.contrib.gis.db.models import GeometryField
from django.contrib.gis.db.models.functions import Transform
from django.contrib.gis.geos import Point
from django.db.models import BooleanField, F, FloatField, Func, QuerySet, Value

from geodata.models import METRIC_SRID


def metric_point(lon: float, lat: float) -> Transform:
    """A WGS84 coordinate projected to METRIC_SRID *by the database*.

    Deliberately not transformed in Python. 4326 -> 5070 includes a WGS84 -> NAD83
    datum step, and the PROJ inside PostGIS and the one GDAL links locally can pick
    different transformations for it -- measured at 0.26 m apart. `geom_m` is projected
    by PostGIS, so the query point must be too, or every distance carries that offset.
    ST_Transform on a constant is folded once per query, so the index is still used.
    """
    point = Value(Point(lon, lat, srid=4326), output_field=GeometryField(srid=4326))
    return Transform(point, METRIC_SRID)


class KnnDistance(Func):
    """`a <-> b`: the index-assisted distance operator, for ORDER BY."""

    arg_joiner = " <-> "
    template = "(%(expressions)s)"
    output_field = FloatField()


class _DWithin(Func):
    """ST_DWithin on METRIC_SRID geometries: a radius in metres, index-assisted."""

    function = "ST_DWithin"
    output_field = BooleanField()


class MetricDistance(Func):
    """ST_Distance on two METRIC_SRID geometries: exact planar metres."""

    function = "ST_Distance"
    output_field = FloatField()


def nearest(queryset: QuerySet, lon: float, lat: float):
    """The feature in `queryset` closest to (lon, lat), with `distance_m` set on it.

    None when the queryset is empty. Filters already applied to the queryset (perennial
    water only, say) are honoured; the KNN scan simply skips rows they exclude.
    """
    value = metric_point(lon, lat)
    return (
        queryset.annotate(distance_m=MetricDistance(F("geom_m"), value))
        .order_by(KnnDistance(F("geom_m"), value))
        .first()
    )


def nearest_distance_m(queryset: QuerySet, lon: float, lat: float) -> float | None:
    """Metres from (lon, lat) to the nearest feature in `queryset`, or None if empty."""
    feature = nearest(queryset, lon, lat)
    return None if feature is None else feature.distance_m


def within(queryset: QuerySet, lon: float, lat: float, metres: float) -> QuerySet:
    """Features within `metres` of (lon, lat), annotated with `distance_m`, nearest first."""
    value = metric_point(lon, lat)
    return (
        queryset.filter(_DWithin(F("geom_m"), value, Value(metres)))
        .annotate(distance_m=MetricDistance(F("geom_m"), value))
        .order_by("distance_m")
    )
