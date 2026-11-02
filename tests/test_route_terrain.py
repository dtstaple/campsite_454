"""
Terrain along a route (TM05-152): exposed and wet stretches by distance along the stitched
line, and the totals the trail panel summarises. The planned multi-trail case is in
test_routing.py, next to its network.
"""

import copy
import json
from pathlib import Path

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Polygon
from rest_framework.test import APIClient

from analysis.analyses import elevation
from geodata.models import METRIC_SRID, TrailRoute
from terrain.along import merge, route_terrain, summarise
from terrain.models import TerrainZone
from terrain.payload import NOTE

X0, Y0 = 1_770_000.0, 2_550_000.0
FORECAST = json.loads((Path(__file__).parent / "fixtures" / "open_meteo_forecast.json").read_text())


# --- the arithmetic, no database --------------------------------------------------------


def test_overlapping_and_touching_pieces_merge_in_route_order():
    assert merge([(800, 1000), (500, 800.5), (2000, 2100), (1100, 1050)]) == [
        [500, 1000],
        [1050, 1100],
        [2000, 2100],
    ]


def test_pieces_further_apart_than_the_gap_stay_separate():
    assert merge([(0, 100), (102, 200)]) == [[0, 100], [102, 200]]


def test_summary_totals_each_kind_and_reports_none_as_zero():
    pieces = [
        ("exposure", "high", 500.0, 800.0),
        ("exposure", "high", 800.0, 1000.0),
        ("exposure", "high", 2000.0, 2100.0),
        ("pooling-risk", "medium", 0.0, 4000.0),  # not a class the panel shows
    ]
    result = summarise(pieces, length_m=4000)
    assert [(s["label"], s["start_m"], s["end_m"]) for s in result["stretches"]] == [
        ("exposed ridge", 500.0, 1000.0),
        ("exposed ridge", 2000.0, 2100.0),
    ]
    totals = {t["layer"]: t for t in result["totals"]}
    assert totals["exposure"]["length_m"] == 600.0
    assert totals["exposure"]["stretches"] == 2
    assert totals["exposure"]["share_pct"] == 15.0
    assert totals["pooling-risk"]["length_m"] == 0.0
    assert totals["pooling-risk"]["label"] == "wet ground"


def test_summary_clips_to_the_line():
    result = summarise([("pooling-risk", "high", -5.0, 50.0)], length_m=40)
    assert result["stretches"][0]["start_m"] == 0.0
    assert result["stretches"][0]["end_m"] == 40.0


# --- against PostGIS --------------------------------------------------------------------


def zone(layer, x0, x1, y0=-50, y1=50, zone_class="high", tile=""):
    square = Polygon.from_bbox((X0 + x0, Y0 + y0, X0 + x1, Y0 + y1))
    square.srid = METRIC_SRID
    return TerrainZone.objects.create(
        region="adirondacks",
        layer=layer,
        zone_class=zone_class,
        tile=tile,
        area_m2=square.area,
        geom=MultiPolygon(square, srid=METRIC_SRID).transform(4326, clone=True),
    )


def line(*coords):
    return LineString([(X0 + x, Y0 + y) for x, y in coords], srid=METRIC_SRID)


@pytest.fixture
def zones():
    zone("exposure", 500, 800)
    zone("exposure", 800, 1000)  # the next tile's piece of the same ridge
    zone("exposure", 2000, 2100)
    zone("pooling-risk", 3000, 3400)
    zone("pooling-risk", 1500, 1700, tile="3-4")  # a run in progress: not merged yet


@pytest.mark.django_db
@pytest.mark.integration
def test_a_line_through_the_zones_gives_stretches_by_distance_along(zones):
    result = route_terrain(line((0, 0), (4000, 0)))
    assert result["status"] == "ok"
    assert result["note"] == NOTE
    got = [(s["layer"], s["start_m"], s["end_m"]) for s in result["stretches"]]
    expected = [
        ("exposure", 500, 1000),
        ("exposure", 2000, 2100),
        ("pooling-risk", 3000, 3400),
    ]
    assert len(got) == len(expected)
    for (layer, a, b), (want_layer, want_a, want_b) in zip(got, expected, strict=True):
        assert layer == want_layer
        assert a == pytest.approx(want_a, abs=1)
        assert b == pytest.approx(want_b, abs=1)
    totals = {t["layer"]: t["length_m"] for t in result["totals"]}
    assert totals["exposure"] == pytest.approx(600, abs=2)
    assert totals["pooling-risk"] == pytest.approx(400, abs=1)


@pytest.mark.django_db
@pytest.mark.integration
def test_an_out_and_back_counts_the_ground_on_both_passes(zones):
    result = route_terrain(line((0, 0), (1200, 0), (0, 0)))
    spans = [(s["start_m"], s["end_m"]) for s in result["stretches"]]
    # Out: 500 to 1000. Back: the same ridge, 1400 to 1900 along the line.
    assert [a for a, _ in spans] == [pytest.approx(500, abs=1), pytest.approx(1400, abs=1)]
    assert [b for _, b in spans] == [pytest.approx(1000, abs=1), pytest.approx(1900, abs=1)]
    exposure = next(t for t in result["totals"] if t["layer"] == "exposure")
    assert exposure["length_m"] == pytest.approx(1000, abs=2)


@pytest.mark.django_db
@pytest.mark.integration
def test_without_terrain_zones_it_says_so():
    result = route_terrain(line((0, 0), (4000, 0)))
    assert result["status"] == "unavailable"
    assert result["reason"]
    assert result["stretches"] == [] and result["totals"] == []


@pytest.fixture
def no_network(monkeypatch):
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


@pytest.mark.django_db
@pytest.mark.integration
def test_the_route_detail_carries_terrain_along(zones, no_network):
    TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/1",
        osm_id=1,
        name="Test Trail",
        geom=MultiLineString(line((0, 0), (4000, 0)), srid=METRIC_SRID).transform(4326, clone=True),
        length_m=4000,
        member_way_ids=[10],
    )
    body = APIClient().get("/api/routes/1/").json()
    along = body["terrain_along"]
    assert along["status"] == "ok"
    assert [s["label"] for s in along["stretches"]] == [
        "exposed ridge",
        "exposed ridge",
        "wet ground",
    ]
    # On the same line as the profile, so the chart can shade it directly.
    assert along["stretches"][-1]["end_m"] <= body["line"]["length_m"] + 0.1
