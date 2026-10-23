"""
A user's own trip-planning data (TM05-80, TM05-81): waypoints they mark on the map, and
overnight plans along a trail.

Everything here belongs to one user. Every foreign key to the user CASCADEs, so deleting
an account removes it all (tests/test_accounts_delete.py checks every relation). Every
query in planning/views.py starts from `request.user`, which is the whole of the
isolation story: there is no URL that names another user.
"""

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GistIndex
from django.db import models

from geodata.models import metric_geom


class Waypoint(models.Model):
    """A point a user marked: a water source, a planned camp, a bail-out, or anything."""

    class Kind(models.TextChoices):
        WATER = "water", "Water"
        CAMP = "camp", "Camp"
        BAILOUT = "bailout", "Bail-out"
        CUSTOM = "custom", "Custom"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="waypoints"
    )
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CUSTOM)
    note = models.TextField(max_length=2000, blank=True, default="")
    geom = gis_models.PointField(srid=4326, spatial_index=True)
    geom_m = metric_geom(gis_models.PointField)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [GistIndex(fields=["geom_m"], name="waypoint_geom_m_gist")]

    def __str__(self):
        return f"{self.name} ({self.kind}) for {self.user}"


class TripPlan(models.Model):
    """Overnight stops along one trail (TM05-81).

    The trail is kept by its stable identity, not a row: a named route by its OSM relation
    id, an assembled trail (TM05-97) by the way it was opened from, or a route planned
    across connected trails (TM05-119) by its route id (routing/service.py). All three
    survive a re-ingest, and the last two have no row to point at. `trail_name` is a
    snapshot for listing plans without resolving every trail.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trip_plans"
    )
    name = models.CharField(max_length=120)
    osm_id = models.BigIntegerField(null=True, blank=True)
    from_way = models.CharField(max_length=64, blank=True, default="")
    planned_route = models.CharField(max_length=255, blank=True, default="")
    trail_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(osm_id__isnull=False)
                | ~models.Q(from_way="")
                | ~models.Q(planned_route=""),
                name="trip_plan_has_a_trail",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.trail_name}) for {self.user}"


class PlanStop(models.Model):
    """One night of a plan: a campsite. The night's number is not stored -- stops are
    ordered by where they fall along the trail each time the plan is read."""

    plan = models.ForeignKey(TripPlan, on_delete=models.CASCADE, related_name="stops")
    campsite = models.ForeignKey(
        "geodata.Campsite",
        on_delete=models.CASCADE,
        related_name="plan_stops",
        null=True,
        blank=True,
    )
    # TM05-99: a potential campsite has no row; its id is its position.
    candidate_id = models.CharField(max_length=64, blank=True, default="")
    point = gis_models.PointField(srid=4326, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "campsite"], name="unique_plan_stop"),
            models.CheckConstraint(
                condition=models.Q(campsite__isnull=False) | ~models.Q(candidate_id=""),
                name="plan_stop_is_a_campsite_or_candidate",
            ),
        ]


class SavedTrail(models.Model):
    """A trail the user saved from the trail panel (TM05-100). Kept by the trail's stable
    identity, like a plan: a route by its OSM relation id, an assembled trail by the way
    it was opened from. `name` is a snapshot for the Profile list."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_trails"
    )
    osm_id = models.BigIntegerField(null=True, blank=True)
    from_way = models.CharField(max_length=64, blank=True, default="")
    name = models.CharField(max_length=255)
    length_m = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(osm_id__isnull=False) | ~models.Q(from_way=""),
                name="saved_trail_has_a_trail",
            ),
            models.UniqueConstraint(
                fields=["user", "osm_id"],
                condition=models.Q(osm_id__isnull=False),
                name="unique_saved_route",
            ),
            models.UniqueConstraint(
                fields=["user", "from_way"],
                condition=models.Q(osm_id__isnull=True),
                name="unique_saved_assembled_trail",
            ),
        ]

    def __str__(self):
        return f"{self.name} saved by {self.user}"


class Hike(models.Model):
    """A recorded hike (TM05-111): the track the phone walked, and its numbers.

    Only ever written when the hiker chooses Save at the end of a hike; nothing is sent
    while one is in progress. `track` is the timestamped points, in segments: a new
    segment starts wherever the recording had a gap (paused, or the page was hidden), so a
    map or GPX file never draws a straight line across time nobody recorded. `geom` is the
    same track as geometry, for the map. The numbers are the ones the hiker saw (computed
    in the browser, frontend/src/tracking/track.ts), stored rather than recomputed so the
    saved hike says exactly what the display said.
    """

    class Mode(models.TextChoices):
        TRAIL = "trail", "Trail"
        FREE = "free", "Free"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hikes"
    )
    name = models.CharField(max_length=120)
    mode = models.CharField(max_length=8, choices=Mode.choices)
    simulated = models.BooleanField(default=False)
    # The trail a trail-mode hike followed, by its stable identity (as for plans), plus a
    # snapshot of its name for the Profile list.
    osm_id = models.BigIntegerField(null=True, blank=True)
    from_way = models.CharField(max_length=64, blank=True, default="")
    trail_name = models.CharField(max_length=255, blank=True, default="")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    elapsed_s = models.FloatField()
    moving_s = models.FloatField()
    distance_m = models.FloatField()
    gain_m = models.FloatField()
    #: [[[lon, lat, ele_m | null, unix_ms], ...], ...]: one list per segment.
    track = models.JSONField()
    geom = gis_models.MultiLineStringField(srid=4326, spatial_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self):
        return f"{self.name} ({self.mode}) by {self.user}"
