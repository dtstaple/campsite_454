"""
GIS models for CampSite vector data.

Design notes:
- All geometry is SRID 4326 (WGS84 lat/lon). Sources arrive in other projections
  (NHD is NAD83/4269, PADUS is Albers/5070) and are reprojected during normalize().
- Multi* geometry variants are used for lines and polygons because external sources
  are inconsistent about single vs multi, and a single geometry stores fine inside a
  Multi container while the reverse fails.
- Every model carries (source, source_id) with a unique constraint. That pair is the
  idempotency key: load() upserts on it so re-running an adapter updates rows instead
  of duplicating them.
- The `raw` JSONField holds the untouched source payload. Typed columns serve scoring
  and API queries; `raw` means a field we didn't anticipate can be backfilled locally
  instead of re-ingesting from the network.
- Every record points at the IngestRun that last wrote it, so provenance is answerable
  per row ("where did this come from, and when") and not just per run. SET_NULL rather
  than CASCADE: pruning old run history must never delete ingested data.

Distances: these are geometry columns in EPSG:4326, so ST_Distance returns DEGREES,
not meters, and a degree of longitude is ~79 km at Adirondack latitude versus ~111 km
for latitude. Never compare raw ST_Distance output when scoring. Cast to geography
(`geom::geography`) or pass spheroid=True to GeoDjango's Distance so results come back
in meters. This is a query-time concern only -- storage and ingestion are unaffected.
"""

from django.contrib.gis.db import models as gis_models
from django.db import models


class SourceRecord(models.Model):
    """Abstract base for anything ingested from an external source."""

    class Source(models.TextChoices):
        RIDB = "ridb", "Recreation.gov (RIDB)"
        OSM = "osm", "OpenStreetMap"
        NHD = "nhd", "USGS NHD"
        PADUS = "padus", "PAD-US"

    source = models.CharField(max_length=16, choices=Source.choices)
    source_id = models.CharField(
        max_length=128,
        help_text="The source's own stable identifier. Upsert key.",
    )
    name = models.CharField(max_length=255, blank=True)
    raw = models.JSONField(
        default=dict,
        blank=True,
        help_text="Untouched source payload, for backfilling fields later.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_run = models.ForeignKey(
        "geodata.IngestRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_records",
        help_text=(
            "The ingest run that most recently created or updated this row. Gives "
            "per-row provenance; region is reachable through it as last_run__region."
        ),
    )

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.name or self.source_id} ({self.source})"


class Campsite(SourceRecord):
    """A single campsite. Point geometry - it's one spot."""

    class SiteType(models.TextChoices):
        DESIGNATED = "designated", "Designated site"
        PRIMITIVE = "primitive", "Primitive / dispersed"
        LEAN_TO = "lean_to", "Lean-to or shelter"
        GROUP = "group", "Group site"
        UNKNOWN = "unknown", "Unknown"

    geom = gis_models.PointField(srid=4326, spatial_index=True)
    site_type = models.CharField(max_length=16, choices=SiteType.choices, default=SiteType.UNKNOWN)
    reservable = models.BooleanField(
        null=True, blank=True, help_text="Null when the source doesn't say."
    )
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "source_id"], name="unique_campsite_source")
        ]
        indexes = [models.Index(fields=["site_type"])]


class Trail(SourceRecord):
    """
    A trail. MultiLineString because OSM splits long trails across many ways and a
    named trail is often several disconnected segments.
    """

    geom = gis_models.MultiLineStringField(srid=4326, spatial_index=True)
    trail_type = models.CharField(
        max_length=32,
        blank=True,
        help_text="Source classification, e.g. path, footway, track, bridleway.",
    )
    length_m = models.FloatField(null=True, blank=True)
    osm_node_ids = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Ordered OSM node IDs. Shared nodes between ways are what make the "
            "routing graph possible in a later sprint - do not drop these."
        ),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "source_id"], name="unique_trail_source")
        ]


class WaterFeature(SourceRecord):
    """
    Water. Generic GeometryField because NHD gives flowlines as lines (streams,
    rivers) and waterbodies as polygons (lakes, ponds), and scoring cares about
    distance to water regardless of shape.
    """

    class FeatureType(models.TextChoices):
        STREAM = "stream", "Stream or river"
        LAKE = "lake", "Lake or pond"
        WETLAND = "wetland", "Wetland"
        SPRING = "spring", "Spring"
        OTHER = "other", "Other"

    geom = gis_models.GeometryField(srid=4326, spatial_index=True)
    feature_type = models.CharField(
        max_length=16, choices=FeatureType.choices, default=FeatureType.OTHER
    )
    perennial = models.BooleanField(
        null=True,
        blank=True,
        help_text=(
            "True if year-round, False if intermittent. Matters a lot for campsite "
            "water access - an intermittent stream is dry when you need it."
        ),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "source_id"], name="unique_water_source")
        ]
        indexes = [models.Index(fields=["feature_type"])]


class PublicLand(SourceRecord):
    """
    Public land boundaries and legal access. MultiPolygon because a single managed
    unit (a national forest, a state forest preserve) is typically many disjoint
    parcels.
    """

    class Access(models.TextChoices):
        OPEN = "open", "Open access"
        RESTRICTED = "restricted", "Restricted access"
        CLOSED = "closed", "Closed"
        UNKNOWN = "unknown", "Unknown"

    geom = gis_models.MultiPolygonField(srid=4326, spatial_index=True)
    manager = models.CharField(
        max_length=128,
        blank=True,
        help_text="Managing agency, e.g. USFS, NPS, BLM, NY DEC.",
    )
    designation = models.CharField(
        max_length=128,
        blank=True,
        help_text="e.g. National Forest, State Forest Preserve, Wilderness Area.",
    )
    public_access = models.CharField(max_length=16, choices=Access.choices, default=Access.UNKNOWN)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "source_id"], name="unique_publicland_source")
        ]
        indexes = [models.Index(fields=["public_access"]), models.Index(fields=["manager"])]


class IngestRun(models.Model):
    """
    Provenance: one row per adapter run. Answers "what data came from where, when,
    and how much of it" - required before the database is trustworthy or reproducible.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"

    source = models.CharField(max_length=16, choices=SourceRecord.Source.choices)
    region = models.CharField(
        max_length=64, help_text="Area-of-interest name from the region config."
    )
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    record_count = models.IntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUCCESS)
    parameters = models.JSONField(
        default=dict,
        blank=True,
        help_text="Bbox, date range, filters, and anything else affecting the result.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "region"]),
            models.Index(fields=["-started_at"]),
        ]
        ordering = ["-started_at"]

    def __str__(self):
        return (
            f"{self.source}/{self.region} @ {self.started_at:%Y-%m-%d %H:%M} ({self.record_count})"
        )
