"""
Tests for campsite enrichment (TM05-64): each derived fact on its own, the slope stencil,
batched terrain, the enrich_campsites command, and the detail endpoint. 3DEP is stubbed:
elevation rises `grade` metres per metre northwards, so slope is known exactly.
"""

import math
from io import StringIO

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon
from django.core.management import call_command
from rest_framework.test import APIClient

from analysis.analyses import elevation
from analysis.analyses.terrain import SiteTerrain, horn_slope
from enrichment.facts import (
    display_name,
    enrich,
    nearest_named_trail,
    nearest_named_water,
    nhd_name,
    osm_tags,
    public_land_unit,
)
from enrichment.models import CampsiteFacts
from geodata.models import Campsite, PublicLand, Trail, TrailRoute, WaterFeature

LON, LAT = -73.85, 44.18
M_PER_DEG_LAT = 111_120


class Terrain:
    grade = 0.0
    calls = 0

    def post(self, points):
        self.calls += 1
        return {
            "samples": [
                {
                    "locationId": i,
                    "value": str(400 + self.grade * (p.y - LAT) * M_PER_DEG_LAT),
                    "resolution": 1,
                    "attributes": {"Name": "TEST"},
                }
                for i, p in enumerate(points)
            ]
        }


@pytest.fixture(autouse=True)
def terrain(monkeypatch):
    stub = Terrain()
    monkeypatch.setattr(elevation, "post_samples", stub.post)
    return stub


def north(metres, lon=LON, lat=LAT):
    return Point(lon, lat + metres / M_PER_DEG_LAT, srid=4326)


def square(half_deg, source_id, name, designation=""):
    ring = Polygon.from_bbox((LON - half_deg, LAT - half_deg, LON + half_deg, LAT + half_deg))
    ring.srid = 4326
    return PublicLand.objects.create(
        source=PublicLand.Source.PADUS,
        source_id=source_id,
        name=name,
        designation=designation,
        manager="State Department of Conservation",
        public_access="open",
        gap_status="1",
        geom=MultiPolygon(ring, srid=4326),
    )


def site(source_id="node/1", name="", tags=None, source=Campsite.Source.OSM):
    return Campsite.objects.create(
        source=source,
        source_id=source_id,
        name=name,
        geom=Point(LON, LAT, srid=4326),
        raw={"type": "node", "tags": tags or {"tourism": "camp_site"}},
    )


def water(metres, name="", raw=None, source_id=None):
    return WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id=source_id or f"w{metres}{name}",
        name=name,
        raw=raw or {},
        geom=north(metres),
        feature_type="stream",
        perennial=True,
    )


def line_at(metres):
    lat = LAT + metres / M_PER_DEG_LAT
    return MultiLineString(LineString((LON - 0.01, lat), (LON + 0.01, lat)), srid=4326)


# --- slope maths (no database) -----------------------------------------------------------


class TestHornSlope:
    def test_flat(self):
        assert horn_slope([5.0] * 9, 10) == (0.0, 0.0)

    def test_a_ten_percent_grade_northwards(self):
        # Rows north to south: +1 m, 0, -1 m over 10 m spacing = 10%.
        z = [1, 1, 1, 0, 0, 0, -1, -1, -1]
        degrees, percent = horn_slope([float(v) for v in z], 10)
        assert percent == pytest.approx(10)
        assert degrees == pytest.approx(math.degrees(math.atan(0.1)))

    def test_direction_does_not_change_the_magnitude(self):
        east = [-1, 0, 1, -1, 0, 1, -1, 0, 1]
        assert horn_slope([float(v) for v in east], 10)[1] == pytest.approx(10)


# --- facts (database) --------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.integration
class TestFacts:
    def test_most_specific_public_land_unit_wins(self):
        square(0.5, "preserve", "Forest Preserve")
        square(0.05, "wilderness", "High Peaks Wilderness", "State Wilderness")
        assert public_land_unit(Point(LON, LAT, srid=4326)).name == "High Peaks Wilderness"

    def test_no_public_land_is_none(self):
        assert public_land_unit(Point(LON, LAT, srid=4326)) is None

    def test_nhd_names_are_read_in_either_case(self):
        flowline = WaterFeature(name="", raw={"gnis_name": "Marcy Brook"})
        waterbody = WaterFeature(name="", raw={"GNIS_NAME": "Marcy Dam Pond"})
        assert nhd_name(flowline) == "Marcy Brook"
        assert nhd_name(waterbody) == "Marcy Dam Pond"

    def test_nearest_named_water_skips_unnamed_and_reads_raw_names(self):
        water(20)  # unnamed, nearer
        water(150, raw={"GNIS_NAME": "Marcy Dam Pond"})  # named only in raw, uppercase
        found = nearest_named_water(LON, LAT)
        assert nhd_name(found) == "Marcy Dam Pond"
        assert found.distance_m == pytest.approx(150, rel=0.02)

    def test_named_water_beyond_five_km_is_none(self):
        water(6000, name="Far Lake")
        assert nearest_named_water(LON, LAT) is None

    def test_a_named_route_is_preferred_over_a_named_way(self):
        Trail.objects.create(source="osm", source_id="way/1", name="Spur", geom=line_at(80))
        TrailRoute.objects.create(
            source="osm",
            source_id="relation/1",
            osm_id=1,
            name="Van Hoevenberg Trail",
            geom=line_at(150),
        )
        trail = nearest_named_trail(LON, LAT)
        assert (trail.name, trail.kind) == ("Van Hoevenberg Trail", "route")

    def test_a_much_closer_named_way_wins(self):
        Trail.objects.create(source="osm", source_id="way/1", name="Spur", geom=line_at(50))
        TrailRoute.objects.create(
            source="osm", source_id="relation/1", osm_id=1, name="Far Route", geom=line_at(900)
        )
        trail = nearest_named_trail(LON, LAT)
        assert (trail.name, trail.kind) == ("Spur", "way")
        assert trail.distance_m == pytest.approx(50, rel=0.02)

    def test_osm_tags_are_extracted_and_shelter_kind_derived(self):
        lean_to = site(tags={"shelter_type": "lean_to", "fireplace": "yes", "operator": "NYS DEC"})
        tags, kind = osm_tags(lean_to)
        assert tags == {"fireplace": "yes", "operator": "NYS DEC"}
        assert kind == "lean-to"
        tent = site("node/2", tags={"tents": "yes", "toilets": "no"})
        assert osm_tags(tent) == ({"tents": "yes", "toilets": "no"}, "tent site")

    def test_tags_the_adapter_already_reads_are_not_repeated(self):
        tags, _ = osm_tags(site(tags={"name": "X", "capacity": "8", "backcountry": "yes"}))
        assert tags == {}

    def test_display_name_keeps_a_source_name(self):
        named = site(name="Marcy Dam")
        assert display_name(named, None, None, None) == ("Marcy Dam", False)

    def test_display_name_for_an_unnamed_site_uses_the_nearest_named_feature(self):
        unnamed = site()
        brook = water(120, name="Marcy Brook")
        brook.distance_m = 120
        assert display_name(unnamed, brook, None, None) == ("Campsite near Marcy Brook", True)

    def test_display_name_falls_back_to_the_land_unit_then_nothing(self):
        unnamed = site()
        land = square(0.05, "w", "High Peaks Wilderness")
        far = water(3000, name="Far Brook")
        far.distance_m = 3000
        assert display_name(unnamed, far, None, land) == ("Campsite in High Peaks Wilderness", True)
        assert display_name(unnamed, None, None, None) == ("", False)


@pytest.mark.django_db
@pytest.mark.integration
class TestEnrich:
    def test_enrich_persists_every_fact_without_touching_the_campsite(self, terrain):
        terrain.grade = 0.10
        square(0.05, "w", "High Peaks Wilderness", "State Wilderness")
        water(90, name="Marcy Brook")
        TrailRoute.objects.create(
            source="osm",
            source_id="relation/1",
            osm_id=1,
            name="Van Hoevenberg Trail",
            geom=line_at(80),
        )
        campsite = site(tags={"tents": "yes", "operator": "NYS DEC"})
        before = (campsite.name, campsite.site_type, campsite.raw)

        facts = enrich(campsite)

        campsite.refresh_from_db()
        assert (campsite.name, campsite.site_type, campsite.raw) == before
        assert facts.land_name == "High Peaks Wilderness"
        assert facts.water_name == "Marcy Brook"
        assert facts.water_distance_m == pytest.approx(90, rel=0.02)
        assert (facts.trail_name, facts.trail_kind) == ("Van Hoevenberg Trail", "route")
        assert facts.slope_pct == pytest.approx(10, abs=0.2)
        assert facts.elevation_m == pytest.approx(400, abs=0.5)
        assert facts.shelter_kind == "tent site"
        assert facts.display_name == "Campsite near Van Hoevenberg Trail"
        assert facts.display_name_derived is True
        assert facts.method_version == "1"

    def test_terrain_failure_leaves_terrain_unknown_but_keeps_other_facts(self, monkeypatch):
        from analysis.base import AnalysisError

        def down(points):
            raise AnalysisError("3DEP down")

        monkeypatch.setattr(elevation, "post_samples", down)
        water(90, name="Marcy Brook")
        facts = enrich(site())
        assert facts.slope_deg is None and facts.elevation_m is None
        assert facts.water_name == "Marcy Brook"
        assert "unavailable" in facts.provenance["terrain"]


@pytest.mark.django_db
@pytest.mark.integration
class TestTerrainBatching:
    def test_run_many_batches_3dep_and_caches(self, terrain, monkeypatch):
        monkeypatch.setattr(elevation, "BATCH_SIZE", 400)
        points = [Point(LON + i * 0.01, LAT, srid=4326) for i in range(50)]  # 450 samples
        first = SiteTerrain().run_many(points)
        assert terrain.calls == 2  # 450 stencil points in batches of 400
        assert all(not outcome.cached for outcome in first)
        second = SiteTerrain().run_many(points)
        assert terrain.calls == 2
        assert all(outcome.cached for outcome in second)


@pytest.mark.django_db
@pytest.mark.integration
class TestCommandAndEndpoint:
    def test_enrich_campsites_reports_coverage_and_is_idempotent(self):
        water(90, name="Marcy Brook")
        site("node/1")
        site("node/2", name="Named Site")
        out = StringIO()
        call_command("enrich_campsites", "adirondacks", stdout=out)
        call_command("enrich_campsites", "adirondacks", stdout=StringIO())
        assert CampsiteFacts.objects.count() == 2
        text = out.getvalue()
        assert "adirondacks: 2 campsites" in text
        assert "named water        2 (100.0%)" in text
        assert "derived for 1 of 1 unnamed" in text

    def test_detail_endpoint_serves_facts_with_unknowns_as_null(self):
        water(90, name="Marcy Brook")
        campsite = site("node/42")
        enrich(campsite)
        body = APIClient().get("/api/campsites/node/42/detail/").json()

        assert body["id"] == "node/42"
        assert body["name"] is None
        assert body["display_name"] == "Campsite near Marcy Brook"
        assert body["display_name_derived"] is True
        facts = body["facts"]
        assert facts["water"]["name"] == "Marcy Brook"
        assert facts["public_land"] is None
        assert facts["trail"] is None
        assert facts["terrain"]["slope_deg"] == pytest.approx(0, abs=0.01)

    def test_detail_for_an_unenriched_site_has_null_facts(self):
        site("campsite/104324", name="H02", source=Campsite.Source.RIDB)
        body = APIClient().get("/api/campsites/campsite/104324/detail/").json()
        assert body["facts"] is None
        assert body["display_name"] == "H02"

    def test_unknown_campsite_is_404(self):
        assert APIClient().get("/api/campsites/node/0/detail/").status_code == 404


@pytest.mark.django_db
@pytest.mark.integration
def test_scoring_and_enrichment_share_one_terrain_cache_entry(terrain):
    """Regression: the slope factor passed {"stencil_m": 10} while enrichment passed {},
    so scoring missed the cache enrichment had filled and called 3DEP for every site."""
    from scoring.config import load
    from scoring.factors import SlopeFactor

    point = Point(LON, LAT, srid=4326)
    SiteTerrain().run_many([point])
    assert terrain.calls == 1
    result = SlopeFactor(load().factor("slope")).evaluate(LON, LAT)
    assert result.measurement["cached"] is True
    assert terrain.calls == 1
