"""
Tests for the named-route endpoints (TM05-60).

Routes and campsites are built in EPSG:5070 metres along a straight east-west line so the
expected "distance along" and "distance from" values are exact. 3DEP and Open-Meteo are
stubbed, so nothing touches the network.
"""

import copy
import json
from pathlib import Path

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, Point
from rest_framework.test import APIClient

from analysis.analyses import elevation
from analysis.base import AnalysisError
from geodata.models import Campsite, TrailRoute

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

X0, Y0 = 1_770_000.0, 2_550_000.0
FORECAST = json.loads((Path(__file__).parent / "fixtures" / "open_meteo_forecast.json").read_text())


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(
        "analysis.analyses.weather.fetch_json", lambda url, params: copy.deepcopy(FORECAST)
    )

    def flat_3dep(points):
        return {
            "samples": [
                {"locationId": i, "value": str(500 + i), "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        }

    monkeypatch.setattr(elevation, "post_samples", flat_3dep)


@pytest.fixture
def client():
    return APIClient()


def metric_point(x, y):
    return Point(X0 + x, Y0 + y, srid=5070).transform(4326, clone=True)


def make_route(osm_id=1, name="Test Trail", length=4000, x=0):
    line = LineString((X0 + x, Y0), (X0 + x + length, Y0), srid=5070)
    geom = MultiLineString(line, srid=5070).transform(4326, clone=True)
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id=f"relation/{osm_id}",
        osm_id=osm_id,
        name=name,
        geom=geom,
        length_m=length,
        member_way_ids=[10, 11],
    )


def make_site(source_id, along, off):
    return Campsite.objects.create(
        source=Campsite.Source.OSM,
        source_id=source_id,
        name=source_id,
        geom=metric_point(along, off),
    )


def bbox_around(route):
    west, south, east, north = route.geom.extent
    return f"{west - 0.01},{south - 0.01},{east + 0.01},{north + 0.01}"


# --- listing -------------------------------------------------------------------------


def test_lists_named_routes_in_the_bbox_as_geojson(client):
    route = make_route()
    make_route(osm_id=2, name="", x=100)  # unnamed: not listed
    make_route(osm_id=3, name="Far Away", x=500_000)

    response = client.get("/api/routes/", {"bbox": bbox_around(route)})

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert [f["id"] for f in body["features"]] == [1]
    feature = body["features"][0]
    assert feature["geometry"]["type"] == "MultiLineString"
    assert feature["properties"]["name"] == "Test Trail"
    assert feature["properties"]["length_m"] == 4000


def test_listing_is_longest_first_and_reports_truncation(client):
    short = make_route(osm_id=1, name="Short", length=1000)
    make_route(osm_id=2, name="Long", length=3000)
    response = client.get("/api/routes/", {"bbox": bbox_around(short), "limit": 1})
    body = response.json()
    assert [f["properties"]["name"] for f in body["features"]] == ["Long"]
    assert body["metadata"]["truncated"] is True


def test_listing_rejects_a_bad_bbox(client):
    assert client.get("/api/routes/", {"bbox": "1,2,3"}).status_code == 400
    assert client.get("/api/routes/").status_code == 400


# --- detail --------------------------------------------------------------------------


def test_detail_includes_profile_stats_and_series(client):
    make_route()
    body = client.get("/api/routes/1/").json()

    assert body["name"] == "Test Trail"
    assert body["line"]["length_m"] == pytest.approx(4000, rel=1e-3)
    profile = body["profile"]
    assert profile["status"] == "ok"
    assert len(profile["distance_m"]) == len(profile["elevation_m"]) == 161
    assert set(profile["stats"]) >= {"gain_m", "loss_m", "high_m", "low_m", "max_grade_pct"}
    assert profile["source"]["name"] == "usgs-3dep"


def test_campsites_are_ordered_along_the_route_with_metre_distances(client):
    make_route()
    make_site("far-end", along=3500, off=100)
    make_site("start", along=200, off=-50)
    make_site("middle", along=2000, off=300)
    make_site("too-far", along=1000, off=800)

    body = client.get("/api/routes/1/").json()
    items = body["campsites"]["items"]

    assert [s["id"] for s in items] == ["start", "middle", "far-end"]
    assert items[0]["distance_along_m"] == pytest.approx(200, abs=1)
    assert items[1]["distance_from_route_m"] == pytest.approx(300, abs=1)
    assert body["campsites"]["within_m"] == 500


def test_campsite_distance_is_configurable_and_capped(client):
    make_route()
    make_site("too-far", along=1000, off=800)
    near = client.get("/api/routes/1/").json()
    wide = client.get("/api/routes/1/", {"campsites_within_m": 1000}).json()
    capped = client.get("/api/routes/1/", {"campsites_within_m": 999999}).json()

    assert near["campsites"]["count"] == 0
    assert wide["campsites"]["count"] == 1
    assert capped["campsites"]["within_m"] == 5000
    assert client.get("/api/routes/1/", {"campsites_within_m": "x"}).status_code == 400


def test_each_campsite_carries_its_score_and_breakdown(client):
    make_route()
    make_site("site", along=1000, off=60)
    item = client.get("/api/routes/1/").json()["campsites"]["items"][0]

    assert isinstance(item["score"], int)
    assert item["score_breakdown"]["contract"] == 1
    assert item["score"] == item["score_breakdown"]["score"]
    keys = [f["key"] for f in item["score_breakdown"]["factors"]]
    assert "water" in keys and "weather" in keys


def test_detail_survives_elevation_being_unavailable(client, monkeypatch):
    def down(points):
        raise AnalysisError("3DEP down")

    monkeypatch.setattr(elevation, "post_samples", down)
    make_route()
    make_site("site", along=1000, off=60)

    response = client.get("/api/routes/1/")
    body = response.json()
    assert response.status_code == 200
    assert body["profile"]["status"] == "unavailable"
    assert "3DEP down" in body["profile"]["reason"]
    assert body["campsites"]["count"] == 1


def test_unknown_route_is_404(client):
    assert client.get("/api/routes/999/").status_code == 404
