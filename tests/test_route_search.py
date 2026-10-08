"""
Trail search and the Discover list (TM05-74): name matching (case- and accent-insensitive),
empty results, ordering by distance from the view centre, and "in or near the view".

Routes are short east-west lines in EPSG:5070 metres at known distances from a centre.
"""

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, Point
from rest_framework.test import APIClient

from analysis.analyses import elevation
from analysis.analyses.elevation import RouteProfile
from api.route_search import grown, normalise
from geodata.models import METRIC_SRID, TrailRoute

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

X0, Y0 = 1_770_000.0, 2_550_000.0


def route(osm_id, name, x, y=0.0, length=1000):
    line = LineString((X0 + x, Y0 + y), (X0 + x + length, Y0 + y), srid=METRIC_SRID)
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id=f"relation/{osm_id}",
        osm_id=osm_id,
        name=name,
        geom=MultiLineString(line.transform(4326, clone=True), srid=4326),
        length_m=length,
        member_way_ids=[osm_id],
    )


def lonlat(x, y=0.0):
    point = Point(X0 + x, Y0 + y, srid=METRIC_SRID).transform(4326, clone=True)
    return f"{point.x:.6f},{point.y:.6f}"


def search(**params):
    return APIClient().get("/api/routes/search/", params)


def names(response):
    return [hit["name"] for hit in response.json()["results"]]


def test_normalise_ignores_case_and_accents():
    assert normalise("Lac Clâir TRAIL") == "lac clair trail"


def test_a_name_search_is_case_and_accent_insensitive_and_needs_every_word():
    route(1, "Lac Clâir Trail", 0)
    route(2, "Mount Marcy Trail", 5000)
    route(3, "Marcy Dam Truck Trail", 9000)
    assert names(search(q="lac clair")) == ["Lac Clâir Trail"]
    assert names(search(q="MARCY trail")) == ["Marcy Dam Truck Trail", "Mount Marcy Trail"]
    assert names(search(q="marcy dam")) == ["Marcy Dam Truck Trail"]


def test_results_carry_name_length_gain_and_centroid():
    route(1, "Mount Marcy Trail", 0, length=2000)
    hit = search(q="marcy").json()["results"][0]
    assert set(hit) == {"osm_id", "name", "length_m", "gain_m", "centroid", "distance_m"}
    assert hit["length_m"] == 2000
    assert hit["gain_m"] is None  # no profile computed yet: never fetched by a search
    assert len(hit["centroid"]) == 2


def test_gain_comes_from_the_cached_profile(monkeypatch):
    monkeypatch.setattr(
        elevation,
        "post_samples",
        lambda points: {
            "samples": [
                {"locationId": i, "value": str(500 + i * 5), "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        },
    )
    marcy = route(1, "Mount Marcy Trail", 0, length=2000)
    RouteProfile().run(marcy.geom)
    assert search(q="marcy").json()["results"][0]["gain_m"] > 0


def test_an_empty_result_is_an_empty_list_not_an_error():
    route(1, "Mount Marcy Trail", 0)
    response = search(q="zzzz")
    assert response.status_code == 200
    assert response.json() == {
        "query": "zzzz",
        "count": 0,
        "total": 0,
        "offset": 0,
        "sort": "name",
        "region": None,
        "truncated": False,
        "unknown": 0,
        "results": [],
    }


def test_results_are_ordered_by_distance_from_the_view_centre():
    route(1, "Far Trail", 20_000)
    route(2, "Near Trail", 1_500)
    route(3, "Middle Trail", 8_000)
    response = search(q="trail", near=lonlat(0))
    assert names(response) == ["Near Trail", "Middle Trail", "Far Trail"]
    distances = [hit["distance_m"] for hit in response.json()["results"]]
    assert distances == sorted(distances)
    assert distances[0] == pytest.approx(1_500, abs=5)


def test_the_discover_list_is_routes_in_or_near_the_view():
    route(1, "In View Trail", 0)
    route(2, "Just Outside Trail", 6_000)  # inside the 50% margin
    route(3, "Far Away Trail", 60_000)
    west, south = (float(v) for v in lonlat(-4_000, -4_000).split(","))
    east, north = (float(v) for v in lonlat(4_000, 4_000).split(","))
    response = search(bbox=f"{west},{south},{east},{north}", near=lonlat(0))
    assert names(response) == ["In View Trail", "Just Outside Trail"]


def test_the_near_margin_grows_the_view_on_every_side():
    assert grown((0, 0, 2, 2)) == (-1, -1, 3, 3)


def test_unnamed_routes_are_never_listed():
    route(1, "", 0)
    route(2, "Named Trail", 100)
    assert names(search(q="trail")) == ["Named Trail"]


@pytest.mark.parametrize(
    "params",
    [{}, {"near": "not,a,point"}, {"q": "x", "near": "500,0"}, {"bbox": "1,2,3"}],
)
def test_bad_requests_are_400(params):
    assert search(**params).status_code == 400
