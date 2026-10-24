"""
The terrain scoring factors (TM05-143): drainage, shelter and view, from a campsite's
TerrainFacts; their weights from config; and how they combine. Legality stays separate.
"""

import dataclasses

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.utils import timezone

from geodata.models import Campsite
from scoring.config import load
from scoring.engine import combine, score_location
from scoring.factors import (
    NOT_AVAILABLE,
    SCORED,
    DrainageFactor,
    ShelterFactor,
    ViewFactor,
)
from scoring.stored import NOT_STORED, TERRAIN_FACTORS, terrain_results
from terrain.models import TerrainFacts, TerrainZone

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

LON, LAT = -73.952, 44.158
CONFIG = load()


def site_with(**facts):
    site = Campsite.objects.create(
        source=Campsite.Source.OSM, source_id="node/1", name="Test", geom=Point(LON, LAT, srid=4326)
    )
    TerrainFacts.objects.create(campsite=site, computed_at=timezone.now(), **facts)
    return Campsite.objects.select_related("terrain").get(pk=site.pk)


def factor(cls):
    return cls(CONFIG.factor(cls.key))


@pytest.mark.parametrize(("level", "score"), [("low", 100), ("medium", 60), ("high", 10)])
def test_drainage_scores_by_pooling_risk_with_its_reason(level, score):
    site = site_with(pooling=level, pooling_reason="Some reason.", values={"twi": 11.0})
    result = factor(DrainageFactor).from_facts(site.terrain)
    assert (result.status, result.score) == (SCORED, score)
    assert result.measurement == {"pooling": level, "twi": 11.0}
    assert result.explanation.startswith(f"Water pooling risk {level}. Some reason.")
    assert "bare-earth" in result.explanation


@pytest.mark.parametrize(
    ("level", "score", "word"),
    [
        ("sheltered", 100, "Sheltered"),
        ("moderate", 75, "Moderate shelter"),
        ("exposed", 35, "Exposed"),
    ],
)
def test_shelter_scores_by_class(level, score, word):
    result = factor(ShelterFactor).from_facts(site_with(shelter=level).terrain)
    assert result.score == score and result.explanation.startswith(word)


def test_view_is_a_modest_bonus_for_area_and_water():
    view = factor(ViewFactor)
    small = view.from_facts(
        site_with(view_area_km2=2.0, view_direction="east", water_view=False).terrain
    )
    assert small.score == 55
    assert small.explanation.startswith("2.0 km² in view, mostly east.")
    TerrainFacts.objects.all().delete()
    Campsite.objects.all().delete()
    wide = view.from_facts(
        site_with(view_area_km2=30.0, view_direction="all around", water_view=True).terrain
    )
    assert wide.score == 100  # 80 + the water bonus of 20
    assert "all around with water in view" in wide.explanation


def test_unknown_facts_are_not_available_and_drop_out():
    terrain = site_with().terrain
    for cls in (DrainageFactor, ShelterFactor, ViewFactor):
        assert factor(cls).from_facts(terrain).status == NOT_AVAILABLE


def test_a_campsite_without_terrain_facts_gets_no_terrain_results():
    site = Campsite.objects.create(
        source=Campsite.Source.OSM, source_id="node/2", name="Bare", geom=Point(LON, LAT, srid=4326)
    )
    assert terrain_results(Campsite.objects.select_related("terrain").get(pk=site.pk)) == {}


def test_terrain_results_cover_the_three_factors_and_are_never_stored():
    site = site_with(pooling="low", shelter="sheltered", view_area_km2=5.0, water_view=True)
    assert set(terrain_results(site)) == TERRAIN_FACTORS == {"drainage", "shelter", "view"}
    assert TERRAIN_FACTORS <= NOT_STORED


def test_a_point_finds_the_facts_of_the_campsite_there():
    site_with(shelter="exposed")
    assert factor(ShelterFactor).evaluate(LON, LAT).score == 35
    assert factor(ShelterFactor).evaluate(LON + 0.01, LAT).status == NOT_AVAILABLE


def test_drainage_at_a_point_without_facts_reads_the_pooling_zones():
    square = Polygon.from_bbox((LON - 0.001, LAT - 0.001, LON + 0.001, LAT + 0.001))
    square.srid = 4326
    TerrainZone.objects.create(
        region="adirondacks", layer="pooling-risk", zone_class="high", area_m2=1,
        geom=MultiPolygon(square, srid=4326),
    )  # fmt: skip
    inside = factor(DrainageFactor).evaluate(LON, LAT)
    assert (inside.status, inside.score) == (SCORED, 10)
    assert "pooling risk zone" in inside.explanation
    assert factor(DrainageFactor).evaluate(LON + 0.01, LAT).status == NOT_AVAILABLE


def test_weights_come_from_config_and_shift_the_total():
    assert CONFIG.weights["drainage"] == 0.10
    assert CONFIG.weights["shelter"] == 0.05
    assert CONFIG.weights["view"] == 0.05
    site = site_with(pooling="high", shelter="exposed", view_area_km2=1.0, water_view=False)
    results = list(terrain_results(site).values())
    base = combine(results, CONFIG, LON, LAT)
    heavier = dataclasses.replace(CONFIG, weights={**CONFIG.weights, "drainage": 1.0})
    reweighted = combine(results, heavier, LON, LAT)
    drainage = next(f for f in reweighted["factors"] if f["key"] == "drainage")
    assert drainage["weight"] == 1.0
    assert reweighted["score"] < base["score"]  # drainage (10) now dominates


def test_terrain_factors_appear_in_the_breakdown_and_legality_stays_separate(monkeypatch):
    site = site_with(pooling="low", shelter="sheltered", view_area_km2=5.0, water_view=True)
    result = score_location(LON, LAT, stored_only=True, evaluated=terrain_results(site))
    keys = {f["key"] for f in result["factors"]}
    assert TERRAIN_FACTORS <= keys
    # The legal gate is computed from the legal factor alone: terrain never moves it.
    without = score_location(LON, LAT, stored_only=True)
    assert result["legal_status"] == without["legal_status"]
    assert result["model_version"] == "1.3.0"
