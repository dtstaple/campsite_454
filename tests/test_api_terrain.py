"""
Terrain facts through the API (TM05-142): the campsite detail's `terrain` block, the
viewshed endpoint, and the badges on a route's campsite rows. Present, partial, missing.
"""

import copy
import json
from pathlib import Path

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon
from django.utils import timezone
from rest_framework.test import APIClient

from analysis.analyses import elevation
from geodata.models import Campsite, TrailRoute
from terrain.models import TerrainFacts
from terrain.payload import NOTE

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

X0, Y0 = 1_770_000.0, 2_550_000.0
FORECAST = json.loads((Path(__file__).parent / "fixtures" / "open_meteo_forecast.json").read_text())


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """As in test_api_routes: no Open-Meteo or 3DEP calls."""
    monkeypatch.setattr(
        "analysis.analyses.weather.fetch_json", lambda url, params: copy.deepcopy(FORECAST)
    )
    monkeypatch.setattr(
        elevation,
        "post_samples",
        lambda points: {
            "samples": [
                {"locationId": i, "value": "500", "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        },
    )


def make_route():
    line = LineString((X0, Y0), (X0 + 4000, Y0), srid=5070)
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/1",
        osm_id=1,
        name="Test Trail",
        geom=MultiLineString(line, srid=5070).transform(4326, clone=True),
        length_m=4000,
        member_way_ids=[10, 11],
    )


def make_site(source_id, along, off):
    return Campsite.objects.create(
        source=Campsite.Source.OSM,
        source_id=source_id,
        name=source_id,
        geom=Point(X0 + along, Y0 + off, srid=5070).transform(4326, clone=True),
    )


@pytest.fixture
def client():
    return APIClient()


def outline(site):
    x, y = site.geom.x, site.geom.y
    square = Polygon.from_bbox((x - 0.01, y - 0.01, x + 0.01, y + 0.01))
    square.srid = 4326
    return MultiPolygon(square, srid=4326)


def full_facts(site):
    return TerrainFacts.objects.create(
        campsite=site,
        computed_at=timezone.now(),
        values={"twi": 6.3, "dev": -0.9},
        pooling="low",
        pooling_reason="Water drains away from here (wetness index 6.3).",
        facing="east",
        sun="morning sun",
        shelter="sheltered",
        shelter_reason="Lies lower than the ground around it, out of the wind.",
        view_area_km2=4.2,
        view_direction="east",
        water_view=True,
        water_view_m2=25000,
        viewshed=outline(site),
    )


def detail(client, site):
    return client.get(f"/api/campsites/{site.source_id}/detail/").json()


def test_detail_carries_every_terrain_fact_with_its_reason_and_the_caveat(client):
    site = make_site("node/1", along=1000, off=60)
    full_facts(site)
    terrain = detail(client, site)["terrain"]
    assert terrain["pooling"] == {
        "level": "low",
        "reason": "Water drains away from here (wetness index 6.3).",
    }
    assert terrain["sun"] == {"facing": "east", "label": "morning sun"}
    assert terrain["shelter"]["level"] == "sheltered"
    assert terrain["view"] == {"area_km2": 4.2, "direction": "east", "water": True}
    assert terrain["has_viewshed"] is True
    assert terrain["note"] == NOTE
    assert "bare-earth" in NOTE and "Trees, buildings and recent changes" in NOTE


def test_partial_facts_are_null_one_by_one(client):
    site = make_site("node/2", along=1000, off=60)
    TerrainFacts.objects.create(campsite=site, computed_at=timezone.now(), pooling="medium")
    terrain = detail(client, site)["terrain"]
    assert terrain["pooling"] == {"level": "medium", "reason": ""}
    assert terrain["sun"] is None
    assert terrain["shelter"] is None
    assert terrain["view"] is None
    assert terrain["has_viewshed"] is False


def test_a_site_without_terrain_facts_has_no_block(client):
    site = make_site("node/3", along=1000, off=60)
    assert detail(client, site)["terrain"] is None


def test_viewshed_is_a_geojson_feature_and_404_without_one(client):
    site = make_site("node/4", along=1000, off=60)
    full_facts(site)
    body = client.get("/api/campsites/node/4/viewshed/").json()
    assert body["type"] == "Feature"
    assert body["geometry"]["type"] == "MultiPolygon"
    assert body["properties"]["water_view"] is True
    assert body["properties"]["note"] == NOTE

    bare = make_site("node/5", along=1500, off=60)
    assert client.get(f"/api/campsites/{bare.source_id}/viewshed/").status_code == 404
    assert client.get("/api/campsites/node/nope/viewshed/").status_code == 404


def test_route_campsite_rows_carry_terrain_badges(client):
    make_route()
    with_facts = make_site("node/6", along=1000, off=60)
    make_site("node/7", along=2000, off=60)
    full_facts(with_facts)
    items = {i["id"]: i for i in client.get("/api/routes/1/").json()["campsites"]["items"]}
    assert items["node/6"]["terrain"] == {
        "pooling": "low",
        "shelter": "sheltered",
        "water_view": True,
    }
    assert items["node/7"]["terrain"] is None
