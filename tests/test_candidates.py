"""
Potential campsites along a trail (TM05-99): each hard filter, the spread rule, an empty
result, the labelling on every candidate, caching, and candidates as overnight stops.

The trail is a straight 4 km east-west line in EPSG:5070 at Adirondack latitudes. Public
land, other trails and water are drawn around it in metres, and 3DEP is stubbed with an
elevation function of position, so which samples pass is exact.
"""

import copy
import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from analysis.analyses import elevation
from geodata.models import METRIC_SRID, PublicLand, Trail, TrailRoute, WaterFeature
from planning import candidates as search
from planning.candidates import LABEL, ROAD_NOTE, config, spread

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

FIXTURES = Path(__file__).parent / "fixtures"
X0, Y0 = 1_770_000.0, 2_550_000.0
LENGTH = 4000
CALLS = []


def metric(geom):
    return geom.transform(METRIC_SRID, clone=True)


def flat(x, y):
    return 500.0


@pytest.fixture
def terrain(monkeypatch):
    """3DEP answers from `terrain.height(x, y)`, in EPSG:5070 metres. Flat at 500 m."""
    forecast = json.loads((FIXTURES / "open_meteo_forecast.json").read_text())
    monkeypatch.setattr(
        "analysis.analyses.weather.fetch_json", lambda url, params: copy.deepcopy(forecast)
    )
    state = {"height": flat}
    CALLS.clear()

    def post(points):
        CALLS.append(len(points))
        # One batched reprojection: GDAL costs ~15 ms a call, whatever its size.
        projected = MultiPoint([Point(p.x, p.y) for p in points], srid=4326)
        projected.transform(METRIC_SRID)
        return {
            "samples": [
                {"locationId": i, "value": str(state["height"](p.x, p.y)), "resolution": 1}
                for i, p in enumerate(projected)
            ]
        }

    monkeypatch.setattr(elevation, "post_samples", post)
    return state


def polygon(x0, y0, x1, y1):
    ring = Polygon.from_bbox((X0 + x0, Y0 + y0, X0 + x1, Y0 + y1))
    ring.srid = METRIC_SRID
    return MultiPolygon(ring.transform(4326, clone=True), srid=4326)


def land(x0=-2000, y0=-2000, x1=LENGTH + 2000, y1=2000, access="open", name="Test Wild Forest"):
    return PublicLand.objects.create(
        source=PublicLand.Source.PADUS,
        source_id=f"padus/{name}/{x0}/{y0}",
        name=name,
        designation="State Wild Forest",
        manager="NYSDEC",
        public_access=access,
        geom=polygon(x0, y0, x1, y1),
    )


def line(x0, y0, x1, y1):
    return LineString((X0 + x0, Y0 + y0), (X0 + x1, Y0 + y1), srid=METRIC_SRID)


@pytest.fixture
def route(terrain):
    geom = MultiLineString(line(0, 0, LENGTH, 0), srid=METRIC_SRID).transform(4326, clone=True)
    Trail.objects.create(
        source=Trail.Source.OSM,
        source_id="way/1",
        name="Test Trail",
        geom=geom,
        length_m=LENGTH,
        osm_node_ids=[1, 2],
    )
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/1",
        osm_id=1,
        name="Test Trail",
        geom=geom,
        length_m=LENGTH,
        member_way_ids=[1],
    )


def find(within=500):
    response = APIClient().get("/api/routes/1/candidates/", {"campsites_within_m": within})
    assert response.status_code == 200, response.content
    return response.json()


def offset_of(candidate):
    point = metric(Point(candidate["lon"], candidate["lat"], srid=4326))
    return point.y - Y0


# --- the search ---------------------------------------------------------------------------


def test_the_test_trail_is_in_the_adirondacks():
    point = Point(X0, Y0, srid=METRIC_SRID).transform(4326, clone=True)
    assert -75.4 <= point.x <= -73.3 and 43.0 <= point.y <= 44.9


def test_candidates_are_found_spread_out_and_capped(route):
    land()
    body = find()
    assert body["status"] == "ok"
    found = body["candidates"]
    assert 1 <= len(found) <= config()["max_results"]
    alongs = [c["distance_along_m"] for c in found]
    assert alongs == sorted(alongs)  # mile order
    gaps = [b - a for a, b in zip(alongs, alongs[1:], strict=False)]
    assert all(gap >= config()["min_spacing_m"] for gap in gaps)
    # Corridor: never farther from the trail than the user's "within".
    assert all(c["distance_from_route_m"] <= 500 for c in found)
    counts = body["counts"]
    assert counts["sampled"] >= counts["passed"] >= counts["scored"] >= len(found)
    # The flattest survivor at each station is scored: one per 200 m station here.
    assert counts["scored"] == LENGTH // config()["sample_spacing_m"] + 1


def test_public_land_filter_keeps_only_open_public_land(route):
    land(y0=-2000, y1=0)  # open land south of the trail only
    land(y0=0, y1=2000, access="restricted", name="Restricted Easement")
    body = find()
    assert body["candidates"]
    assert all(offset_of(c) < 0 for c in body["candidates"])
    assert body["counts"]["rejected"]["public_land"] > 0


def test_trail_filter_keeps_150_ft_from_every_trail(route):
    land()
    Trail.objects.create(
        source=Trail.Source.OSM,
        source_id="way/2",
        name="Parallel Path",
        geom=MultiLineString(line(0, 120, LENGTH, 120).transform(4326, clone=True)),
        length_m=LENGTH,
        osm_node_ids=[3, 4],
    )
    body = find()
    assert body["counts"]["rejected"]["trail"] > 0
    for candidate in body["candidates"]:
        assert abs(offset_of(candidate) - 120) > 45.7
        assert abs(offset_of(candidate)) > 45.7


def test_water_filter_keeps_150_ft_from_water(route):
    land()
    WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id="nhd/1",
        name="Test Brook",
        geom=line(0, -200, LENGTH, -200).transform(4326, clone=True),
        feature_type=WaterFeature.FeatureType.STREAM,
        perennial=True,
    )
    body = find()
    assert body["counts"]["rejected"]["water"] > 0
    assert all(abs(offset_of(c) + 200) > 45.7 for c in body["candidates"])


def test_elevation_filter_applies_the_dec_4000_ft_rule_with_its_margin(route, terrain):
    land()
    terrain["height"] = lambda x, y: 1210.0  # 3,970 ft: within 50 ft of 4,000
    body = find()
    assert body["candidates"] == []
    assert body["counts"]["rejected"]["elevation"] == body["counts"]["sampled"] - sum(
        body["counts"]["rejected"][k] for k in ("public_land", "trail", "water")
    )
    assert body["reason"] == "No open public land below the DEC elevation limits within 500 m."


def test_elevation_filter_applies_the_high_peaks_3500_ft_rule(route, terrain):
    land(name="High Peaks Wilderness")
    terrain["height"] = lambda x, y: 1100.0  # 3,609 ft: fine elsewhere, not in the High Peaks
    assert find()["candidates"] == []


def test_slope_filter_rejects_steep_ground(route, terrain):
    land()
    # North of the trail rises at 20 degrees; south is flat.
    terrain["height"] = lambda x, y: 500 + max(0.0, y - Y0) * 0.364
    body = find()
    assert body["counts"]["rejected"]["slope"] > 0
    assert body["candidates"] and all(offset_of(c) < 0 for c in body["candidates"])
    assert all(c["slope_deg"] <= config()["max_slope_deg"] for c in body["candidates"])


def test_an_empty_result_says_why(route, terrain):
    terrain["height"] = lambda x, y: 500 + (y - Y0) * 0.5  # 27 degrees everywhere
    assert find()["reason"] == "No public land with open access within 500 m of this trail."
    land()
    body = find(within=1000)
    assert body["candidates"] == []
    assert body["reason"] == ("No public land with gentle slope (≤ 5°) within 1 km of this trail.")


def test_every_candidate_is_labelled_unverified_with_its_checks(route):
    land()
    found = find()["candidates"]
    assert found
    for candidate in found:
        assert candidate["kind"] == "candidate"
        assert candidate["label"] == LABEL == "Potential spot (unverified)"
        assert candidate["confidence"]["level"] == "computed"
        assert candidate["not_checked"] == ROAD_NOTE
        assert ROAD_NOTE == "Road distance isn't checked; verify current rules on the ground."
        assert [c["key"] for c in candidate["checks"]] == [
            "public_land",
            "trail",
            "water",
            "elevation",
            "slope",
        ]
        assert all(check["passed"] for check in candidate["checks"])
        assert candidate["id"].startswith("candidate/")
        assert candidate["score"] is not None


def test_the_answer_is_cached_per_route_and_corridor(route):
    land()
    first = find()
    calls = len(CALLS)
    second = find()
    assert first["cached"] is False and second["cached"] is True
    assert second["candidates"] == first["candidates"]
    assert len(CALLS) == calls  # no 3DEP on the cached answer
    assert find(within=1000)["cached"] is False  # a different corridor is a new search


def test_bad_requests():
    assert APIClient().get("/api/routes/999/candidates/").status_code == 404
    assert APIClient().get("/api/trails/way/999/candidates/").status_code == 404


def test_a_bad_corridor_is_400(route):
    assert (
        APIClient().get("/api/routes/1/candidates/", {"campsites_within_m": "x"}).status_code == 400
    )


# --- the spread rule (pure) -------------------------------------------------------------------


def c(id, along, score):
    return {"id": id, "distance_along_m": along, "score": score}


def test_spread_keeps_the_best_at_least_the_spacing_apart():
    picked = spread(
        [c("a", 0, 80), c("b", 300, 95), c("c", 900, 70), c("d", 1000, 90), c("e", 2000, 60)],
        805,
        8,
    )
    # b (95) first; then d (90) is 700 m from b: too close; a (80) 300 m: too close;
    # c (70) is 600 m: too close; e (60) is 1,700 m: kept.
    assert [p["id"] for p in picked] == ["b", "e"]


def test_spread_caps_the_count_and_returns_mile_order():
    many = [c(str(i), i * 1000, 100 - i) for i in range(20)]
    picked = spread(many, 805, 8)
    assert [p["id"] for p in picked] == [str(i) for i in range(8)]
    assert spread(list(reversed(many)), 805, 3) == spread(many, 805, 3)


def test_sampling_stays_inside_the_corridor():
    trail = line(0, 0, 1000, 0)
    samples = search.sample_points(trail, 200, config())
    assert {s["offset_m"] for s in samples} == {60, 120, 200}
    assert {s["side"] for s in samples} == {"left", "right"}
    assert all(abs(s["y"] - Y0) <= 200 + 1e-6 for s in samples)


# --- as overnight stops ---------------------------------------------------------------------


def signed_in():
    user = get_user_model().objects.create_user(username="hiker", password="a-strong-passw0rd!")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
    return client


def test_a_candidate_as_a_night_carries_the_unverified_warning(route):
    land()
    candidate = find()["candidates"][0]
    client = signed_in()
    plan = client.post(
        "/api/plans/", {"osm_id": 1, "stop_ids": [candidate["id"]], "name": "Wild"}, format="json"
    )
    assert plan.status_code == 201, plan.content
    body = plan.json()
    (stop,) = body["stops"]
    assert stop["kind"] == "candidate"
    assert stop["display_name"] == "Potential spot (unverified)"
    assert stop["legality"]["verdict"] == "unknown"
    assert stop["warning"].startswith("Night 1, Potential spot (unverified): a computed spot")
    assert "road distance isn't checked" in stop["warning"]
    assert body["warnings"] == [stop["warning"]]

    reopened = client.get(f"/api/plans/{body['id']}/").json()
    assert reopened["stops"][0]["id"] == candidate["id"]
    gpx = client.get(f"/api/plans/{body['id']}/gpx/").content.decode()
    assert "<type>overnight-stop:unverified</type>" in gpx


def test_a_malformed_candidate_id_is_rejected(route):
    response = signed_in().post(
        "/api/plans/preview/", {"osm_id": 1, "stop_ids": ["candidate/abc"]}, format="json"
    )
    assert response.status_code == 400
    assert "not a potential campsite id" in response.json()["error"]
