"""
What the terrain pipeline stores (TM05-141): derived answers only, never rasters.

- TerrainRun    provenance for one `make terrain`: tool versions, DEM source, grids,
                parameters, timings, memory and counts
- TerrainFacts  per campsite: the sampled values, the classes built from them, and the
                viewshed outline
- TerrainZone   classified polygons (pooling risk, exposure), served as vector tiles
- TerrainTile   one finished tile of one tool, so an interrupted run resumes where it
                stopped
"""

from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GistIndex
from django.db import models

from geodata.models import Campsite, metric_geom


class TerrainRun(models.Model):
    region = models.CharField(max_length=64, db_index=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    #: The registry digest (terrain/registry.py) and the DEM source digest: tile results
    #: are reused only under the same pair.
    config_digest = models.CharField(max_length=16)
    dem_digest = models.CharField(max_length=12)
    #: geolibre-wasm and runtime versions, the runtime's sha256, wasmtime's version.
    tool_versions = models.JSONField(default=dict)
    #: Source tiles with their URLs, Last-Modified and sizes.
    dem_source = models.JSONField(default=dict)
    #: tools.yml as run.
    config = models.JSONField(default=dict)
    #: Per tool: seconds, tiles, peak WASM memory in MB.
    timings = models.JSONField(default=dict)
    #: Sites with each fact, zone polygons per layer and class, and so on.
    counts = models.JSONField(default=dict)
    peak_rss_mb = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self):
        return f"{self.region} terrain run {self.started_at:%Y-%m-%d %H:%M}"


class TerrainTile(models.Model):
    """A tool finished on a tile. Its facts and zone pieces are already written."""

    region = models.CharField(max_length=64)
    tool = models.CharField(max_length=64)
    tile = models.CharField(max_length=16, help_text="'<ix>-<iy>' in the tool's grid.")
    config_digest = models.CharField(max_length=16)
    dem_digest = models.CharField(max_length=12)
    run = models.ForeignKey(TerrainRun, on_delete=models.SET_NULL, null=True, blank=True)
    seconds = models.FloatField()
    peak_memory_mb = models.FloatField()
    finished_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["region", "tool", "tile", "config_digest", "dem_digest"],
                name="unique_terrain_tile",
            )
        ]


class TerrainFacts(models.Model):
    """Per-campsite terrain facts. Every field can be unknown, and unknown is not zero."""

    class Pooling(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class Shelter(models.TextChoices):
        SHELTERED = "sheltered", "Sheltered"
        MODERATE = "moderate", "Moderate"
        EXPOSED = "exposed", "Exposed"

    campsite = models.OneToOneField(
        Campsite, on_delete=models.CASCADE, primary_key=True, related_name="terrain"
    )
    run = models.ForeignKey(TerrainRun, on_delete=models.SET_NULL, null=True, blank=True)
    computed_at = models.DateTimeField()
    #: Raw sampled values by fact name (tools.yml `facts`): twi, sink_depth_m, slope_deg,
    #: aspect_deg, dev, ... A new tool's facts land here with no migration.
    values = models.JSONField(default=dict, blank=True)

    pooling = models.CharField(max_length=8, choices=Pooling.choices, blank=True)
    pooling_reason = models.CharField(max_length=160, blank=True)
    #: "east", "southwest", ... or "flat"; blank when unknown.
    facing = models.CharField(max_length=16, blank=True)
    sun = models.CharField(max_length=48, blank=True)
    shelter = models.CharField(max_length=10, choices=Shelter.choices, blank=True)
    shelter_reason = models.CharField(max_length=160, blank=True)
    view_area_km2 = models.FloatField(null=True, blank=True)
    #: The sector holding the most visible ground, or "all around".
    view_direction = models.CharField(max_length=16, blank=True)
    water_view = models.BooleanField(null=True, blank=True)
    water_view_m2 = models.FloatField(null=True, blank=True)
    #: What the terrain lets you see from the site, simplified; for "Show what I can see".
    viewshed = gis_models.MultiPolygonField(srid=4326, null=True, blank=True)

    def __str__(self):
        return f"terrain facts for campsite {self.campsite_id}"


class TerrainZone(models.Model):
    """One classified polygon: a stretch of ground where, say, pooling risk is high."""

    region = models.CharField(max_length=64)
    layer = models.CharField(max_length=32, help_text="tools.yml zones.layer, e.g. exposure.")
    zone_class = models.CharField(max_length=16, help_text="tools.yml zones class, e.g. high.")
    #: The tile it was cut from while the run is in progress; blank once merged.
    tile = models.CharField(max_length=16, blank=True)
    run = models.ForeignKey(TerrainRun, on_delete=models.SET_NULL, null=True, blank=True)
    area_m2 = models.FloatField()
    geom = gis_models.MultiPolygonField(srid=4326, spatial_index=True)
    geom_m = metric_geom(gis_models.MultiPolygonField)

    class Meta:
        indexes = [
            models.Index(fields=["region", "layer", "tile"]),
            GistIndex(fields=["geom_m"], name="terrainzone_geom_m_gist"),
        ]

    def __str__(self):
        return f"{self.layer} {self.zone_class} zone in {self.region}"
