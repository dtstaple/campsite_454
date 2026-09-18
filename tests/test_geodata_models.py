"""
Schema tests for the geodata GIS models.

These assert the behaviour the models promise rather than their field declarations:
that every geometry column accepts valid SRID 4326 geometry and hands it back
unchanged, and that (source, source_id) is genuinely enforced by the database as an
idempotency key. The second part is what makes an adapter's load() safe to re-run --
if the constraint were missing, a rerun would silently duplicate rows instead of
failing loudly here.

Marked integration because they need a live PostGIS database; geometry is built
inline so there are no fixtures and no network.
"""

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon
from django.db import IntegrityError, transaction
from django.utils import timezone

from geodata.models import (
    Campsite,
    IngestRun,
    PublicLand,
    SourceRecord,
    Trail,
    WaterFeature,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

# Coordinates in the Adirondacks, the first target region.
ADK_POINT = Point(-74.05, 44.11, srid=4326)
ADK_LINE = LineString((-74.05, 44.11), (-74.04, 44.12), (-74.03, 44.14), srid=4326)
ADK_RING = Polygon(
    ((-74.06, 44.10), (-74.02, 44.10), (-74.02, 44.15), (-74.06, 44.15), (-74.06, 44.10)),
    srid=4326,
)


def test_campsite_saves_and_returns_point():
    site = Campsite.objects.create(
        source=Campsite.Source.RIDB,
        source_id="ridb-12345",
        name="Marcy Dam",
        geom=ADK_POINT,
        site_type=Campsite.SiteType.LEAN_TO,
        capacity=8,
    )
    site.refresh_from_db()

    assert site.geom.srid == 4326
    assert site.geom.equals_exact(ADK_POINT, tolerance=1e-9)
    assert site.pk is not None
    # Unset optionals stay null rather than defaulting to a wrong value.
    assert site.reservable is None


def test_trail_saves_multilinestring_and_preserves_node_order():
    node_ids = [1001, 1002, 1003, 1004]
    trail = Trail.objects.create(
        source=Trail.Source.OSM,
        source_id="way/98765",
        name="Van Hoevenberg Trail",
        geom=MultiLineString(ADK_LINE, srid=4326),
        trail_type="path",
        osm_node_ids=node_ids,
    )
    trail.refresh_from_db()

    assert trail.geom.srid == 4326
    assert trail.geom.num_geom == 1
    # Order matters -- these node IDs are what makes routing possible later.
    assert trail.osm_node_ids == node_ids


@pytest.mark.parametrize(
    "geom",
    [
        pytest.param(ADK_LINE, id="flowline"),
        pytest.param(ADK_RING, id="waterbody"),
    ],
)
def test_waterfeature_accepts_both_lines_and_polygons(geom):
    """NHD gives streams as lines and lakes as polygons; one generic column takes both."""
    water = WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id=f"nhd-{geom.geom_type}",
        geom=geom,
        feature_type=WaterFeature.FeatureType.STREAM,
        perennial=True,
    )
    water.refresh_from_db()

    assert water.geom.srid == 4326
    assert water.geom.geom_type == geom.geom_type


def test_publicland_saves_multipolygon():
    land = PublicLand.objects.create(
        source=PublicLand.Source.PADUS,
        source_id="padus-555",
        name="High Peaks Wilderness",
        geom=MultiPolygon(ADK_RING, srid=4326),
        manager="NY DEC",
        public_access=PublicLand.Access.OPEN,
    )
    land.refresh_from_db()

    assert land.geom.srid == 4326
    assert land.geom.num_geom == 1
    assert land.geom.area > 0


def test_ingestrun_records_provenance():
    run = IngestRun.objects.create(
        source=SourceRecord.Source.RIDB,
        region="adirondacks",
        started_at=timezone.now(),
        record_count=42,
        parameters={"bbox": [-74.5, 43.8, -73.5, 44.5]},
    )
    run.refresh_from_db()

    assert run.status == IngestRun.Status.SUCCESS
    assert run.record_count == 42
    assert run.parameters["bbox"][0] == -74.5
    assert run.finished_at is None


# (model, kwargs) pairs covering every table that carries the idempotency key.
DUPLICATE_CASES = [
    pytest.param(Campsite, {"geom": ADK_POINT}, id="campsite"),
    pytest.param(Trail, {"geom": MultiLineString(ADK_LINE, srid=4326)}, id="trail"),
    pytest.param(WaterFeature, {"geom": ADK_LINE}, id="waterfeature"),
    pytest.param(PublicLand, {"geom": MultiPolygon(ADK_RING, srid=4326)}, id="publicland"),
]


@pytest.mark.parametrize("model,extra", DUPLICATE_CASES)
def test_duplicate_source_pair_is_rejected(model, extra):
    """The database, not application code, has to enforce the upsert key."""
    fields = {"source": model.Source.OSM, "source_id": "duplicate-me", **extra}
    model.objects.create(**fields)

    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(**fields)


@pytest.mark.parametrize("model,extra", DUPLICATE_CASES)
def test_same_source_id_from_a_different_source_is_allowed(model, extra):
    """Only the pair is unique -- two sources may legitimately reuse an identifier."""
    model.objects.create(source=model.Source.OSM, source_id="shared-id", **extra)
    model.objects.create(source=model.Source.NHD, source_id="shared-id", **extra)

    assert model.objects.filter(source_id="shared-id").count() == 2


@pytest.mark.parametrize("model,extra", DUPLICATE_CASES)
def test_records_are_filterable_by_the_region_of_their_ingest_run(model, extra):
    """Per-row provenance: region comes through the FK, so no denormalised column."""
    adk = IngestRun.objects.create(
        source=SourceRecord.Source.OSM, region="adirondacks", started_at=timezone.now()
    )
    alaska = IngestRun.objects.create(
        source=SourceRecord.Source.OSM, region="alaska", started_at=timezone.now()
    )
    model.objects.create(source=model.Source.OSM, source_id="in-adk", last_run=adk, **extra)
    model.objects.create(source=model.Source.OSM, source_id="in-ak", last_run=alaska, **extra)

    assert model.objects.filter(last_run__region="adirondacks").count() == 1
    assert model.objects.get(last_run__region="alaska").source_id == "in-ak"
    # Reverse accessor is named per concrete model via the %(class)s placeholder.
    assert getattr(adk, f"{model._meta.model_name}_records").count() == 1


def test_pruning_run_history_nulls_the_link_instead_of_deleting_data():
    """SET_NULL, not CASCADE -- deleting old provenance must never drop ingested rows."""
    run = IngestRun.objects.create(
        source=SourceRecord.Source.RIDB, region="adirondacks", started_at=timezone.now()
    )
    site = Campsite.objects.create(
        source=Campsite.Source.RIDB, source_id="ridb-1", geom=ADK_POINT, last_run=run
    )

    run.delete()
    site.refresh_from_db()

    assert Campsite.objects.filter(pk=site.pk).exists()
    assert site.last_run_id is None
