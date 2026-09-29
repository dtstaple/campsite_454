"""
Admin for the ingested models.

The point of these is not that Django's admin works -- it does -- but that *our*
configuration of it does. A bad `list_display` entry, a `list_filter` on a field that no
longer exists, or a search field pointing at a renamed column all raise only when
someone opens the page, which in practice means during a demo.
"""

import pytest
from django.contrib import admin
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from geodata.models import Campsite, IngestRun, PublicLand, Trail, WaterFeature

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

INGESTED_MODELS = [Campsite, Trail, WaterFeature, PublicLand, IngestRun]


@pytest.fixture
def staff_client():
    User = get_user_model()
    user = User.objects.create_superuser(username="admin", password="a-strong-passw0rd!")
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def one_of_each():
    run = IngestRun.objects.create(
        source=Campsite.Source.OSM,
        region="adirondacks",
        started_at=timezone.now(),
        finished_at=timezone.now(),
        record_count=4,
    )
    line = LineString((-74.05, 44.10), (-74.04, 44.11), srid=4326)
    square = Polygon.from_bbox((-74.05, 44.10, -74.04, 44.11))
    square.srid = 4326
    return {
        "campsite": Campsite.objects.create(
            source=Campsite.Source.OSM,
            source_id="node/1",
            name="Wanika Falls",
            geom=Point(-74.05, 44.10, srid=4326),
            last_run=run,
        ),
        "trail": Trail.objects.create(
            source=Trail.Source.OSM,
            source_id="way/1",
            name="Van Hoevenberg",
            geom=MultiLineString(line, srid=4326),
            last_run=run,
        ),
        "water": WaterFeature.objects.create(
            source=WaterFeature.Source.NHD,
            source_id="w1",
            name="Marcy Brook",
            geom=line,
            last_run=run,
        ),
        "land": PublicLand.objects.create(
            source=PublicLand.Source.PADUS,
            source_id="p1",
            name="High Peaks Wilderness",
            geom=MultiPolygon(square, srid=4326),
            last_run=run,
        ),
        "run": run,
    }


@pytest.mark.parametrize("model", INGESTED_MODELS)
def test_every_ingested_model_is_registered(model):
    """The gap this closes: for two sprints none of these were browsable at all."""
    assert model in site._registry, f"{model.__name__} is not registered in the admin"


@pytest.mark.parametrize("model", INGESTED_MODELS)
def test_the_admin_configuration_is_valid(model):
    """Runs Django's own admin checks, which catch a list_display or list_filter
    naming a field that does not exist -- the failure mode that only shows up when
    someone opens the page."""
    errors = site._registry[model].check()

    assert not errors, [str(e) for e in errors]


@pytest.mark.parametrize("model", INGESTED_MODELS)
def test_the_changelist_loads(staff_client, one_of_each, model):
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")

    response = staff_client.get(url)

    assert response.status_code == 200


@pytest.mark.parametrize("model", INGESTED_MODELS)
def test_the_change_form_loads(staff_client, one_of_each, model):
    """Geometry is read-only and summarised; rendering the real widget for a large
    multipolygon is what makes this page unusable."""
    obj = model.objects.first()
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_change", args=[obj.pk])

    response = staff_client.get(url)

    assert response.status_code == 200


@pytest.mark.parametrize("model", [Campsite, Trail, WaterFeature, PublicLand])
def test_search_by_name_and_by_source_id(staff_client, one_of_each, model):
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
    obj = model.objects.first()

    by_name = staff_client.get(url, {"q": obj.name})
    by_source_id = staff_client.get(url, {"q": obj.source_id})

    assert by_name.status_code == 200
    assert by_source_id.status_code == 200
    assert obj.name.encode() in by_name.content
    assert obj.name.encode() in by_source_id.content


def test_ingest_runs_show_source_region_status_and_count(staff_client, one_of_each):
    url = reverse("admin:geodata_ingestrun_changelist")

    content = staff_client.get(url).content.decode()

    assert "adirondacks" in content
    for column in ("source", "region", "status", "record_count"):
        assert column in admin.site._registry[IngestRun].list_display or column in content


def test_geometry_summary_describes_the_shape_without_rendering_a_map(one_of_each):
    summary = site._registry[PublicLand].geometry_summary(one_of_each["land"])

    assert "MultiPolygon" in summary
    assert "SRID 4326" in summary
    assert "centroid" in summary


def test_geometry_summary_handles_a_missing_geometry():
    """An unsaved row with no geometry must not 500 the change form."""
    assert site._registry[Campsite].geometry_summary(Campsite()) == "—"


def test_region_column_falls_back_when_there_is_no_provenance_row(one_of_each):
    orphan = Campsite.objects.create(
        source=Campsite.Source.RIDB,
        source_id="campsite/999",
        name="Orphan",
        geom=Point(-74.0, 44.0, srid=4326),
    )

    assert site._registry[Campsite].region(orphan) == "—"
    assert site._registry[Campsite].region(one_of_each["campsite"]) == "adirondacks"
