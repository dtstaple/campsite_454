"""
Derived location facts per campsite (TM05-64).

Kept in their own one-to-one table, never written into Campsite: Campsite holds what the
source said, and an ingest re-run overwrites it. Facts are what we *worked out* from our
other tables and from 3DEP -- recomputable, versioned and dated. Every field is nullable
or blank because every fact can be unknown, and unknown is not the same as zero.
"""

from django.db import models

from geodata.models import Campsite


class CampsiteFacts(models.Model):
    campsite = models.OneToOneField(
        Campsite, on_delete=models.CASCADE, primary_key=True, related_name="facts"
    )
    method_version = models.CharField(max_length=16)
    computed_at = models.DateTimeField()

    # The most specific public land unit containing the site.
    land_name = models.CharField(max_length=255, blank=True)
    land_manager = models.CharField(max_length=128, blank=True)
    land_designation = models.CharField(max_length=128, blank=True)
    land_access = models.CharField(max_length=16, blank=True)
    land_gap_status = models.CharField(max_length=1, blank=True)
    land_source_id = models.CharField(max_length=128, blank=True)

    # Nearest named water.
    water_name = models.CharField(max_length=255, blank=True)
    water_distance_m = models.FloatField(null=True, blank=True)
    water_feature_type = models.CharField(max_length=16, blank=True)
    water_perennial = models.BooleanField(null=True, blank=True)
    water_source_id = models.CharField(max_length=128, blank=True)

    # Nearest named trail: a named hiking route ("route") or an OSM way ("way").
    trail_name = models.CharField(max_length=255, blank=True)
    trail_distance_m = models.FloatField(null=True, blank=True)
    trail_kind = models.CharField(max_length=8, blank=True)
    trail_source_id = models.CharField(max_length=128, blank=True)

    # From 3DEP via the site_terrain analysis.
    elevation_m = models.FloatField(null=True, blank=True)
    slope_deg = models.FloatField(null=True, blank=True)
    slope_pct = models.FloatField(null=True, blank=True)

    # OSM tags the campsite adapter does not read into Campsite columns.
    osm_tags = models.JSONField(default=dict, blank=True)
    # "lean-to" or "tent site", derived from those tags; blank when they do not say.
    shelter_kind = models.CharField(max_length=16, blank=True)

    # The source name when there is one; otherwise "Campsite near <named feature>".
    display_name = models.CharField(max_length=255, blank=True)
    display_name_derived = models.BooleanField(default=False)

    provenance = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name_plural = "campsite facts"

    def __str__(self):
        return f"facts for {self.campsite_id} (v{self.method_version})"
