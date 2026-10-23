"""
The routable trail graph (TM05-119), derived from the ingested trails.

A Trail row is one OSM way, and its `osm_node_ids` line up with its vertices. Ways that
share a node meet there. An edge is the stretch of one way between two such nodes (or a
way's end): nothing joins or leaves it in between. `build_trail_graph <region>` cuts the
ways into edges and measures each one's climb from 3DEP; only those answers are kept, the
elevation samples at about 50 m spacing included, never the raster.
"""

from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GistIndex
from django.db import models

from geodata.models import Trail, metric_geom


class TrailGraphBuild(models.Model):
    """One run of build_trail_graph: what it made, from what, and how long it took."""

    region = models.CharField(max_length=64, db_index=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    ways = models.IntegerField(default=0)
    ways_skipped = models.IntegerField(default=0)
    nodes = models.IntegerField(default=0)
    edges = models.IntegerField(default=0)
    elevation_samples = models.IntegerField(default=0)
    elevation_nodata = models.IntegerField(default=0)
    provenance = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self):
        return f"{self.region} graph built {self.started_at:%Y-%m-%d %H:%M}"


class TrailEdge(models.Model):
    """One walkable piece of trail between two graph nodes, in the way's direction.

    `ascent_m` is the climb walking start -> end and `descent_m` the drop; the other way
    round they swap. `node_ids` and the geometry keep every vertex of the stretch, so a
    route can start or end at any of them. `samples` are [distance along m, elevation m]
    pairs from 3DEP, with the gaps filled.
    """

    build = models.ForeignKey(TrailGraphBuild, on_delete=models.CASCADE, related_name="trail_edges")
    region = models.CharField(max_length=64, db_index=True)
    trail = models.ForeignKey(Trail, on_delete=models.CASCADE, related_name="graph_edges")
    start_node = models.BigIntegerField(db_index=True)
    end_node = models.BigIntegerField(db_index=True)
    start_index = models.IntegerField(help_text="Vertex index in the way where it starts.")
    end_index = models.IntegerField(help_text="Vertex index in the way where it ends.")
    node_ids = models.JSONField(default=list)
    name = models.CharField(max_length=255, blank=True)
    length_m = models.FloatField()
    ascent_m = models.FloatField(default=0.0)
    descent_m = models.FloatField(default=0.0)
    samples = models.JSONField(default=list, blank=True)
    geom = gis_models.LineStringField(srid=4326, spatial_index=True)
    geom_m = metric_geom(gis_models.LineStringField)

    class Meta:
        indexes = [GistIndex(fields=["geom_m"], name="trailedge_geom_m_gist")]
        constraints = [
            models.UniqueConstraint(
                fields=["region", "trail", "start_index"], name="unique_edge_per_way_start"
            )
        ]

    def __str__(self):
        return f"{self.name or self.trail.source_id} {self.start_node}->{self.end_node}"
