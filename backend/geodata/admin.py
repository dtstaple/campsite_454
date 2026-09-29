"""
Admin for the ingested data.

Exists so the team can look at what the pipeline actually loaded without writing a
query -- browse 83,000 features, inspect one record, and read the ingest history. It is
also how a data problem gets spotted early: a run that loaded a tenth of what it should,
or a layer whose names are all blank, is obvious in a changelist and invisible in a test.

Three things here are about surviving the real dataset rather than a fixture:

- `show_full_result_count = False`. Django otherwise runs a second unfiltered COUNT(*)
  to render "1 of 63,407" next to a filtered result. On the water table that is a
  sequential scan on every page view.
- `geom` is never in `list_display` and is read-only on the form. GeoDjango's default
  widget renders an editable OpenLayers map per geometry field, which for a 230-part
  multipolygon is a long wait to look at a row. `geometry_summary` gives the useful part
  -- type, vertex count, centroid -- in one line.
- `last_run` is a `raw_id_field`. As a dropdown it would load every IngestRun on every
  form.
"""

from django.contrib import admin
from django.contrib.gis.db import models as gis_models
from django.forms import TextInput

from geodata.models import Campsite, IngestRun, PublicLand, Trail, WaterFeature


class SourceRecordAdmin(admin.ModelAdmin):
    """Shared behaviour for the four ingested models."""

    # Every one of these tables is large enough that the extra count hurts.
    show_full_result_count = False
    list_select_related = ("last_run",)
    raw_id_fields = ("last_run",)
    readonly_fields = ("geometry_summary", "created_at", "updated_at")
    exclude = ("geom",)
    date_hierarchy = "updated_at"

    # source_id is matched exactly so the query uses the (source, source_id) unique
    # index; name is a substring match because that is how a person looks for a place.
    search_fields = ("name", "=source_id")

    # A geometry column would otherwise render as an editable map widget.
    formfield_overrides = {gis_models.GeometryField: {"widget": TextInput}}

    @admin.display(description="Geometry")
    def geometry_summary(self, obj):
        """Type, size and centroid -- enough to tell a good row from a broken one."""
        geom = obj.geom
        if geom is None:
            return "—"
        centroid = geom.centroid
        parts = f", {geom.num_geom} parts" if geom.num_geom > 1 else ""
        return (
            f"{geom.geom_type} (SRID {geom.srid}, {geom.num_points} points{parts}) "
            f"centroid {centroid.x:.4f}, {centroid.y:.4f}"
        )

    @admin.display(description="Region", ordering="last_run__region")
    def region(self, obj):
        """Which area of interest this row came from, via its provenance row."""
        return obj.last_run.region if obj.last_run_id else "—"


@admin.register(Campsite)
class CampsiteAdmin(SourceRecordAdmin):
    list_display = ("name", "source", "source_id", "site_type", "reservable", "capacity", "region")
    list_filter = ("source", "site_type", "reservable")


@admin.register(Trail)
class TrailAdmin(SourceRecordAdmin):
    list_display = ("name", "source", "source_id", "trail_type", "length_m", "region")
    list_filter = ("source", "trail_type")


@admin.register(WaterFeature)
class WaterFeatureAdmin(SourceRecordAdmin):
    list_display = ("name", "source", "source_id", "feature_type", "perennial", "region")
    list_filter = ("source", "feature_type", "perennial")


@admin.register(PublicLand)
class PublicLandAdmin(SourceRecordAdmin):
    list_display = ("name", "manager", "designation", "public_access", "gap_status", "region")
    # gap_status and public_access answer different questions -- what the land is managed
    # for, and whether you may enter -- so both are worth filtering on.
    list_filter = ("public_access", "gap_status", "source")


@admin.register(IngestRun)
class IngestRunAdmin(admin.ModelAdmin):
    """Provenance. The first place to look when a layer has the wrong number of rows."""

    list_display = ("source", "region", "status", "record_count", "started_at", "duration")
    list_filter = ("source", "status", "region")
    search_fields = ("region", "notes")
    date_hierarchy = "started_at"
    readonly_fields = ("duration",)

    @admin.display(description="Duration")
    def duration(self, obj):
        if not obj.finished_at or not obj.started_at:
            return "—"
        seconds = int((obj.finished_at - obj.started_at).total_seconds())
        return f"{seconds // 60}m {seconds % 60}s" if seconds >= 60 else f"{seconds}s"
