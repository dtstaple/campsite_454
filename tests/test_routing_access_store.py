"""
Campsite access difficulty stored by the pipeline (TM05-171): `compute_access <region>`
over a built graph, and the campsite panel's `access` object.

The network is tests/test_routing.py's: the West Trail runs 1 km east from (0, 0) to a
junction, where the Ridge Trail climbs 300 m over 1 km north. The Island Trail, at
x = 5000, joins nothing. One trailhead, "West Lot", is at the West Trail's start.
"""

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient
from test_routing import campsite, flat_profile_3dep, network, to_4326  # noqa: F401 (fixtures)

from enrichment.models import CampsiteFacts
from geodata.models import Landmark
from routing.access_store import compute_region

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def trailhead(source_id, name, x, y):
    return Landmark.objects.create(
        source=Landmark.Source.OSM,
        source_id=source_id,
        name=name,
        kind=Landmark.Kind.TRAILHEAD,
        geom=to_4326(x, y),
    )


def enriched(source_id, x, y):
    site = campsite(source_id, x, y)
    CampsiteFacts.objects.create(campsite=site, method_version="1", computed_at=timezone.now())
    return site


def facts(source_id):
    return CampsiteFacts.objects.get(campsite__source_id=source_id)


@pytest.fixture
def sites(network):  # noqa: F811
    trailhead("node/th1", "West Lot", 5, 5)
    enriched("node/easy", 500, 20)  # 0.5 km along the flat West Trail
    enriched("node/ridge", 1000, 980)  # near the Ridge Trail's top: 2 km, 294 m of climb
    enriched("node/island", 5500, 10)  # on the Island Trail: no trailhead joins it
    enriched("node/far", 9000, 9000)  # nowhere near a trail
    campsite("node/unenriched", 500, 30)  # no facts row yet: skipped


def test_each_site_is_classified_from_the_trailhead(sites):
    summary = compute_region("adirondacks")
    assert summary.trailheads == summary.trailheads_joined == 1
    assert summary.campsites == 4

    easy = facts("node/easy")
    assert easy.access_class == "easy"
    assert easy.access_trailhead == "West Lot"
    assert easy.access_distance_m == pytest.approx(520, abs=5)
    assert easy.access_gain_m == 0
    assert "West Lot" in easy.access_reason

    ridge = facts("node/ridge")
    assert ridge.access_class == "moderate"  # 300 m of climb is past easy's 200 m
    assert ridge.access_distance_m == pytest.approx(1980, abs=5)
    assert ridge.access_gain_m == pytest.approx(294, abs=3)
    assert ridge.access_time_s > ridge.access_distance_m / (5000 / 3600)


def test_an_unreachable_site_is_unknown_never_guessed(sites):
    compute_region("adirondacks")
    for source_id in ("node/island", "node/far"):
        row = facts(source_id)
        assert row.access_class == "unknown"
        assert row.access_distance_m is None and row.access_time_s is None
        assert row.access_reason


def test_without_trailheads_every_site_is_unknown(network):  # noqa: F811
    enriched("node/easy", 500, 20)
    compute_region("adirondacks")
    assert facts("node/easy").access_class == "unknown"


def test_the_command_reports_counts_and_is_repeatable(sites, capsys):
    call_command("compute_access", "adirondacks")
    call_command("compute_access", "adirondacks")
    out = capsys.readouterr().out
    assert "Easy access" in out and "Access unknown" in out
    assert CampsiteFacts.objects.exclude(access_class="").count() == 4


def test_the_campsite_panel_shows_access(sites):
    before = APIClient().get("/api/campsites/node/easy/detail/").json()
    assert before["access"] is None  # not computed yet

    compute_region("adirondacks")
    body = APIClient().get("/api/campsites/node/easy/detail/").json()
    assert body["access"]["class"] == "easy"
    assert body["access"]["label"] == "Easy access"
    assert body["access"]["trailhead"] == "West Lot"
    assert body["access"]["reason"]

    unknown = APIClient().get("/api/campsites/node/island/detail/").json()["access"]
    assert unknown["class"] == "unknown"
    assert unknown["label"] == "Access unknown"
    assert unknown["distance_m"] is None
