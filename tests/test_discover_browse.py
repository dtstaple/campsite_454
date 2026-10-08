"""
The Discover page's browsing (TM05-102), through the TM05-74/85 search endpoint: region
filtering from regions.yml, sorting, pagination, and the card data.
"""

from datetime import UTC, datetime

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, Point
from rest_framework.test import APIClient

from analysis.analyses import elevation
from analysis.analyses.elevation import RouteProfile
from enrichment.models import RouteFacts
from geodata.models import METRIC_SRID, Campsite, TrailRoute
from pipeline.regions import load_regions

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

#: Inside each region's box (regions.yml), far from the other.
ADIRONDACKS = (-74.0, 44.1)
WHITE_MOUNTAINS = (-71.4, 44.2)


@pytest.fixture(autouse=True)
def climbing_3dep(monkeypatch):
    monkeypatch.setattr(
        elevation,
        "post_samples",
        lambda points: {
            "samples": [
                {"locationId": i, "value": str(500 + i), "resolution": 1}
                for i in range(len(points))
            ]
        },
    )


def route(osm_id, name, where, length=1000, dx=0.0):
    start = Point(where[0] + dx, where[1], srid=4326).transform(METRIC_SRID, clone=True)
    line = LineString((start.x, start.y), (start.x + length, start.y), srid=METRIC_SRID)
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id=f"relation/{osm_id}",
        osm_id=osm_id,
        name=name,
        geom=MultiLineString(line, srid=METRIC_SRID).transform(4326, clone=True),
        length_m=length,
        member_way_ids=[osm_id * 10],
    )


def facts(route, gain=None, difficulty="", route_type="out_and_back"):
    return RouteFacts.objects.create(
        route=route,
        computed_at=datetime.now(UTC),
        length_m=route.length_m,
        gain_m=gain,
        difficulty=difficulty,
        route_type=route_type,
    )


def browse(**params):
    response = APIClient().get("/api/routes/search/", params)
    assert response.status_code == 200, response.content
    return response.json()


def names(body):
    return [r["name"] for r in body["results"]]


def test_region_filtering_uses_regions_yml():
    assert "adirondacks" in load_regions() and "white-mountains-nh" in load_regions()
    route(1, "Adirondack Trail", ADIRONDACKS)
    route(2, "Franconia Trail", WHITE_MOUNTAINS)
    assert names(browse(region="adirondacks")) == ["Adirondack Trail"]
    assert names(browse(region="white-mountains-nh")) == ["Franconia Trail"]
    assert browse(region="white-mountains-nh")["region"] == "white-mountains-nh"


def test_an_unknown_region_is_a_400():
    response = APIClient().get("/api/routes/search/", {"region": "atlantis"})
    assert response.status_code == 400
    assert "Unknown region" in response.json()["error"]


def test_sort_by_length_gain_name_and_distance():
    short = route(1, "B Short", ADIRONDACKS, length=500)
    long = route(2, "A Long", ADIRONDACKS, length=3000, dx=0.05)
    mid = route(3, "C Middle", ADIRONDACKS, length=1500, dx=0.1)
    facts(short, gain=300)
    facts(long, gain=100)  # mid has no gain known: sorts last on gain
    assert names(browse(region="adirondacks", sort="length")) == ["A Long", "C Middle", "B Short"]
    assert names(browse(region="adirondacks", sort="gain")) == ["B Short", "A Long", "C Middle"]
    assert names(browse(region="adirondacks", sort="name")) == ["A Long", "B Short", "C Middle"]
    near_mid = f"{ADIRONDACKS[0] + 0.1},{ADIRONDACKS[1]}"
    assert names(browse(region="adirondacks", sort="distance", near=near_mid))[0] == "C Middle"
    assert mid.pk  # used above


def test_bad_sorts_are_400():
    route(1, "A", ADIRONDACKS)
    for params in ({"sort": "height"}, {"sort": "distance"}):
        response = APIClient().get("/api/routes/search/", {"region": "adirondacks", **params})
        assert response.status_code == 400


def test_pages_with_offset_and_total():
    for n in range(1, 8):
        route(n, f"Trail {n}", ADIRONDACKS, length=100 * n, dx=n * 0.01)
    first = browse(region="adirondacks", sort="length", limit=3)
    second = browse(region="adirondacks", sort="length", limit=3, offset=3)
    last = browse(region="adirondacks", sort="length", limit=3, offset=6)
    assert first["total"] == 7 and first["truncated"] is True
    assert names(first) == ["Trail 7", "Trail 6", "Trail 5"]
    assert names(second) == ["Trail 4", "Trail 3", "Trail 2"]
    assert names(last) == ["Trail 1"] and last["truncated"] is False


def test_card_data():
    marcy = route(1, "Marcy Trail", ADIRONDACKS, length=2000)
    plain = route(2, "Plain Trail", ADIRONDACKS, dx=0.2)
    facts(marcy, gain=150, difficulty="hard", route_type="loop")
    RouteProfile().run(marcy.geom)  # the stored profile the sparkline reads
    on_trail = Point(ADIRONDACKS[0], ADIRONDACKS[1], srid=4326)
    for i in range(3):
        Campsite.objects.create(
            source=Campsite.Source.OSM, source_id=f"node/{i}", name="", geom=on_trail
        )
    body = browse(region="adirondacks", sort="name", cards=1)
    card = body["results"][0]
    assert card["name"] == "Marcy Trail"
    assert (card["difficulty"], card["route_type"]) == ("hard", "loop")
    assert card["campsites"] == 3 and card["campsites_within_m"] == 500
    spark = card["sparkline"]
    assert 2 <= len(spark) <= 32 and spark == sorted(spark)  # the stub climbs steadily
    assert spark[0] == pytest.approx(500, abs=1)
    other = body["results"][1]
    assert other["name"] == "Plain Trail"
    assert (other["difficulty"], other["sparkline"], other["campsites"]) == (None, None, 0)
    assert plain.pk


def test_without_cards_there_is_no_card_data():
    route(1, "A", ADIRONDACKS)
    assert "sparkline" not in browse(region="adirondacks")["results"][0]


def test_the_regions_endpoint_lists_regions_yml_with_trail_counts():
    route(1, "Adirondack Trail", ADIRONDACKS)
    regions = APIClient().get("/api/regions/").json()
    assert [r["id"] for r in regions] == list(load_regions())
    by_id = {r["id"]: r for r in regions}
    assert by_id["adirondacks"]["trails"] == 1
    assert by_id["white-mountains-nh"]["trails"] == 0
    assert by_id["adirondacks"]["label"] == load_regions()["adirondacks"].label
