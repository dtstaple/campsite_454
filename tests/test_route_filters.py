"""
Filters on the Discover list (TM05-85): each filter on its own, filters combined, clearing
them, and routes whose stored facts cannot answer a filter (counted as unknown).

Routes are given RouteFacts directly, so each filter's effect is exact.
"""

from datetime import UTC, datetime

import pytest
from django.contrib.gis.geos import LineString, MultiLineString
from django.core.management import call_command
from rest_framework.test import APIClient

from analysis.analyses import elevation
from enrichment.models import RouteFacts
from geodata.models import METRIC_SRID, Campsite, TrailRoute

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

X0, Y0 = 1_770_000.0, 2_550_000.0


def route(osm_id, name, length, gain=None, difficulty="", kind="point_to_point", nearest=None):
    line = LineString((X0, Y0 + osm_id * 100), (X0 + length, Y0 + osm_id * 100), srid=METRIC_SRID)
    created = TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id=f"relation/{osm_id}",
        osm_id=osm_id,
        name=name,
        geom=MultiLineString(line.transform(4326, clone=True), srid=4326),
        length_m=length,
        member_way_ids=[osm_id],
    )
    RouteFacts.objects.create(
        route=created,
        computed_at=datetime(2026, 10, 8, tzinfo=UTC),
        length_m=length,
        gain_m=gain,
        difficulty=difficulty,
        route_type=kind,
        nearest_campsite_m=nearest,
    )
    return created


@pytest.fixture
def trails():
    route(1, "Short Easy Loop", 1_500, gain=50, difficulty="easy", kind="loop", nearest=200)
    route(
        2, "Long Hard Out", 12_000, gain=1_000, difficulty="hard", kind="out_and_back", nearest=900
    )
    route(3, "Mid Moderate Through", 6_000, gain=400, difficulty="moderate", nearest=None)
    route(4, "Unprofiled Trail", 5_000, gain=None, difficulty="", kind="out_and_back", nearest=300)


def names(**params):
    body = APIClient().get("/api/routes/search/", {"q": "", "bbox": "-180,-89,179,89", **params})
    assert body.status_code == 200, body.content
    data = body.json()
    return sorted(hit["name"] for hit in data["results"]), data["unknown"]


def test_no_filters_lists_everything(trails):
    found, unknown = names()
    assert len(found) == 4
    assert unknown == 0


def test_length_range(trails):
    assert names(min_length_m=5_000, max_length_m=7_000)[0] == [
        "Mid Moderate Through",
        "Unprofiled Trail",
    ]


def test_gain_range_leaves_out_routes_with_no_profile_and_counts_them(trails):
    found, unknown = names(min_gain_m=300)
    assert found == ["Long Hard Out", "Mid Moderate Through"]
    assert unknown == 1  # Unprofiled Trail: no gain known


def test_difficulty(trails):
    assert names(difficulty="easy,hard")[0] == ["Long Hard Out", "Short Easy Loop"]


def test_route_type(trails):
    found, unknown = names(route_type="out_and_back")
    assert found == ["Long Hard Out", "Unprofiled Trail"]
    assert unknown == 0  # route type needs no profile


def test_has_campsites_within(trails):
    assert names(campsites_within_m=500)[0] == ["Short Easy Loop", "Unprofiled Trail"]


def test_filters_combine(trails):
    found, _ = names(route_type="out_and_back", campsites_within_m=1000, min_length_m=10_000)
    assert found == ["Long Hard Out"]
    assert names(difficulty="moderate", route_type="loop")[0] == []


def test_clearing_the_filters_restores_the_full_list(trails):
    assert names(difficulty="easy")[0] == ["Short Easy Loop"]
    assert len(names()[0]) == 4


def test_a_route_with_no_stored_facts_is_unknown_to_fact_filters_but_kept_by_length():
    line = LineString((X0, Y0), (X0 + 2_000, Y0), srid=METRIC_SRID)
    TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/9",
        osm_id=9,
        name="Factless Trail",
        geom=MultiLineString(line.transform(4326, clone=True), srid=4326),
        length_m=2_000,
        member_way_ids=[9],
    )
    assert names(route_type="loop") == ([], 1)
    assert names(max_length_m=3_000)[0] == ["Factless Trail"]


@pytest.mark.parametrize(
    "params",
    [
        {"difficulty": "brutal"},
        {"route_type": "spiral"},
        {"min_gain_m": "lots"},
        {"max_length_m": "-1"},
    ],
)
def test_bad_filter_values_are_400(params):
    response = APIClient().get("/api/routes/search/", {"q": "x", **params})
    assert response.status_code == 400


def test_opening_a_trail_and_enrich_routes_store_its_facts(monkeypatch):
    monkeypatch.setattr(
        elevation,
        "post_samples",
        lambda points: {
            "samples": [
                {"locationId": i, "value": str(500 + i * 10), "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        },
    )
    line = LineString((X0, Y0), (X0 + 4_000, Y0), srid=METRIC_SRID).transform(4326, clone=True)
    opened = TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/5",
        osm_id=5,
        name="Opened Trail",
        geom=MultiLineString(line, srid=4326),
        length_m=4_000,
        member_way_ids=[5],
    )
    Campsite.objects.create(source="osm", source_id="node/1", geom=line.interpolate(0.5))

    APIClient().get("/api/routes/5/")
    facts = RouteFacts.objects.get(route=opened)
    assert facts.gain_m > 0
    assert facts.difficulty in {"easy", "moderate", "hard"}
    assert facts.nearest_campsite_m == pytest.approx(0, abs=1)

    RouteFacts.objects.all().delete()
    call_command("enrich_routes", "adirondacks")  # cached profile only: no new 3DEP call
    refreshed = RouteFacts.objects.get(route=opened)
    assert refreshed.gain_m == pytest.approx(facts.gain_m)
    assert refreshed.route_type == facts.route_type
