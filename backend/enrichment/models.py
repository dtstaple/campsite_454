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

    # TM05-171: how hard the site is to reach on foot from the nearest reachable trailhead,
    # over the routing graph (`compute_access <region>`, routing/access.py). Blank class
    # means not computed yet; "unknown" means no trailhead connects, and then the walk's
    # figures are null, never guessed.
    access_class = models.CharField(max_length=16, blank=True, db_index=True)
    access_reason = models.TextField(blank=True)
    access_trailhead = models.CharField(max_length=255, blank=True)
    access_distance_m = models.FloatField(null=True, blank=True)
    access_gain_m = models.FloatField(null=True, blank=True)
    access_time_s = models.FloatField(null=True, blank=True)

    provenance = models.JSONField(default=dict, blank=True)

    # The vector-data factor results of the site's score, stored-only, so scoring a map's
    # worth of campsites is a combine rather than ~40 ms of searches each (TM05-86,
    # scoring/stored.py). `factor_digest` names the factor settings they came from; any
    # other value means they are stale and are recomputed on next use.
    factor_results = models.JSONField(default=list, blank=True)
    factor_digest = models.CharField(max_length=16, blank=True)

    class Meta:
        verbose_name_plural = "campsite facts"

    def __str__(self):
        return f"facts for {self.campsite_id} (v{self.method_version})"


class RouteFacts(models.Model):
    """Derived facts per named route (TM05-85), what the Discover filters read.

    Stored rather than computed per request: route type needs a stitched line and end
    queries (~30 ms a route), difficulty needs the elevation profile. `enrich_routes`
    fills the table, and opening a trail refreshes its row. Null means not known yet --
    usually because the route's profile has never been computed -- never zero.
    """

    route = models.OneToOneField(
        "geodata.TrailRoute", on_delete=models.CASCADE, primary_key=True, related_name="facts"
    )
    computed_at = models.DateTimeField()
    length_m = models.FloatField()
    gain_m = models.FloatField(null=True, blank=True)
    loss_m = models.FloatField(null=True, blank=True)
    difficulty = models.CharField(max_length=16, blank=True)
    shenandoah = models.FloatField(null=True, blank=True)
    route_type = models.CharField(max_length=16)
    route_type_estimated = models.BooleanField(default=True)
    #: Distance to the nearest campsite within NEAREST_CAMPSITE_MAX_M; null if none.
    nearest_campsite_m = models.FloatField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["difficulty"]),
            models.Index(fields=["route_type"]),
        ]
