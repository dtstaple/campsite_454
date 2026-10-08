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
