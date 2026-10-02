"""
The analysis cache (TM05-44).

One row is one computed *answer* -- "the forecast for this grid cell for these three
days", later "the slope at this campsite" -- never the raw material behind it. Raster
pixels and API payloads are not kept; the derived value and a record of how it was made
are. This is the "store answers, not raw material" decision in docs/architecture.md.
"""

from django.contrib.gis.db import models as gis_models
from django.db import models


class AnalysisResult(models.Model):
    #: sha256 of the canonical (analysis, version, geometry, window, params) -- see
    #: analysis.base.cache_key(). The one column a lookup needs.
    key = models.CharField(max_length=64, unique=True)

    analysis = models.CharField(max_length=64, help_text="Analysis name, e.g. weather.")
    version = models.CharField(max_length=32, help_text="Analysis version that computed this.")
    geom = gis_models.GeometryField(
        srid=4326, spatial_index=True, help_text="The (quantised) geometry analysed."
    )
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    params = models.JSONField(default=dict, blank=True)

    value = models.JSONField(help_text="The computed answer.")
    provenance = models.JSONField(
        help_text="What was used, when, and with what parameters: source, request, "
        "response metadata, computed_at."
    )

    computed_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [models.Index(fields=["analysis", "expires_at"])]

    def __str__(self):
        return f"{self.analysis} {self.key[:8]} (expires {self.expires_at:%Y-%m-%d %H:%M})"
