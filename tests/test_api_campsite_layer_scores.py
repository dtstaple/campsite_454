"""
Tests for the score on the map's campsite features (TM05-86).

The layer must score each feature from stored values only, through the same code path as
the detail endpoint, so the map and the panel never disagree. Setup fills the stores from
stubs, then the network is closed: every 3DEP, Open-Meteo and requests call is recorded
and fails, so each test proves the request made no live call.
"""

import pytest
import requests
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient
from test_api_campsite_score import LAT, LON, Network, campsite, surroundings

from analysis.analyses import elevation, weather
from analysis.analyses.weather import WeatherForecast
from enrichment.facts import enrich
from enrichment.models import CampsiteFacts
from geodata.models import Campsite, WaterFeature
from scoring.config import load, parse
from scoring.stored import NOT_STORED, factors_digest

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

BBOX = f"{LON - 0.05},{LAT - 0.05},{LON + 0.05},{LAT + 0.05}"


@pytest.fixture(autouse=True)
def network(monkeypatch):
    stub = Network()
    monkeypatch.setattr(elevation, "post_samples", stub.post_samples)
    monkeypatch.setattr(weather, "fetch_json", stub.fetch_json)
    monkeypatch.setattr(requests.Session, "request", stub.request)
    return stub


def scored_site(source_id="node/1"):
    """An enriched site whose terrain and weather answers are already cached."""
    site = campsite(source_id)
    enrich(site)
    WeatherForecast().run(site.geom, {"days": load().factor("weather")["forecast_days"]})
    return site


def campsite_features(query=""):
    response = APIClient().get(f"/api/campsites/?bbox={BBOX}{query}")
    assert response.status_code == 200
    return response.json()


def map_data_campsites():
    response = APIClient().get(f"/api/map-data/?bbox={BBOX}&layers=campsites")
    assert response.status_code == 200
    return response.json()["layers"]["campsites"]


def by_id(document):
    return {feature["id"]: feature["properties"] for feature in document["features"]}


def detail(source_id):
    return APIClient().get(f"/api/campsites/{source_id}/detail/").json()


def test_scored_site_carries_the_same_score_as_the_panel(network):
    surroundings()
    scored_site()
    network.open = False

    panel = detail("node/1")
    for document in (campsite_features(), map_data_campsites()):
        properties = by_id(document)["node/1"]
        assert properties["score_status"] == "scored"
        assert isinstance(properties["score"], int) and 0 <= properties["score"] <= 100
        assert properties["score"] == panel["score"]
    assert network.calls == []


def test_existing_properties_are_unchanged_and_scores_come_last(network):
    surroundings()
    scored_site()
    network.open = False

    properties = by_id(campsite_features())["node/1"]

    assert list(properties) == [
        "name",
        "site_type",
        "reservable",
        "capacity",
        "score",
        "score_status",
    ]
    assert properties["name"] == "Test Site"


def test_unenriched_site_is_null_with_a_status_never_zero(network):
    surroundings()
    campsite("campsite/104324")
    network.open = False

    for document in (campsite_features(), map_data_campsites()):
        properties = by_id(document)["campsite/104324"]
        assert properties["score"] is None
        assert properties["score_status"] == "pending"
    assert network.calls == []


def test_scored_and_unscored_sites_in_one_response(network):
    surroundings()
    scored_site("node/1")
    campsite("campsite/2")
    network.open = False

    properties = by_id(campsite_features())

    assert properties["node/1"]["score_status"] == "scored"
    assert properties["node/1"]["score"] is not None
    assert properties["campsite/2"]["score"] is None
    assert properties["campsite/2"]["score_status"] == "pending"
    assert network.calls == []


def test_capped_response_keeps_the_cap_and_scores_only_what_it_returns(network):
    surroundings()
    for i in range(5):
        site = campsite(f"node/{i}")
        site.geom = Point(LON + i * 0.001, LAT, srid=4326)
        site.save()
        enrich(site)
    network.open = False

    document = campsite_features("&limit=2")

    assert document["metadata"]["returned"] == 2
    assert document["metadata"]["matched"] == 5
    assert document["metadata"]["truncated"] is True
    assert len(document["features"]) == 2
    for properties in by_id(document).values():
        assert properties["score_status"] == "scored"
        assert properties["score"] is not None
    assert network.calls == []


def test_cap_picks_the_same_features_with_and_without_scores(network):
    """Scoring must not change which features the deterministic sample returns."""
    surroundings()
    for i in range(5):
        site = campsite(f"node/{i}")
        site.geom = Point(LON + i * 0.001, LAT, srid=4326)
        site.save()
    network.open = False

    first = campsite_features("&limit=3")
    network.open = True
    for site in Campsite.objects.all():
        enrich(site)
    network.open = False
    second = campsite_features("&limit=3")

    assert [f["id"] for f in first["features"]] == [f["id"] for f in second["features"]]
    assert {p["score_status"] for p in by_id(first).values()} == {"pending"}
    assert {p["score_status"] for p in by_id(second).values()} == {"scored"}


def test_empty_area_has_no_features_and_no_scoring(network):
    network.open = False

    response = APIClient().get("/api/campsites/?bbox=-140.00,10.00,-139.90,10.10")

    assert response.status_code == 200
    assert response.json()["features"] == []
    assert network.calls == []


def test_other_layers_have_no_score_properties(network):
    surroundings()
    network.open = False

    response = APIClient().get(f"/api/map-data/?bbox={BBOX}&layers=trails,water,public-land")

    for layer in response.json()["layers"].values():
        for feature in layer["features"]:
            assert "score" not in feature["properties"]
            assert "score_status" not in feature["properties"]


def test_enrich_stores_the_vector_factor_results():
    surroundings()
    facts = enrich(campsite())

    # Slope and weather (analysis cache) and the terrain factors (TM05-143) aren't stored.
    assert {entry["key"] for entry in facts.factor_results} == set(load().weights) - NOT_STORED
    assert facts.factor_digest == factors_digest()


def test_map_and_panel_score_from_the_stored_results(network):
    """Removing the water after enrichment changes nothing: the request combines what was
    stored rather than searching again."""
    surroundings()
    scored_site()
    network.open = False
    before = by_id(campsite_features())["node/1"]["score"]

    WaterFeature.objects.all().delete()

    assert by_id(campsite_features())["node/1"]["score"] == before
    assert detail("node/1")["score"] == before
    water = next(f for f in detail("node/1")["score_breakdown"]["factors"] if f["key"] == "water")
    assert water["status"] == "scored"


def test_stale_results_are_recomputed_once_and_written_back(network):
    surroundings()
    scored_site()
    CampsiteFacts.objects.update(factor_results=[], factor_digest="stale")
    network.open = False

    properties = by_id(campsite_features())["node/1"]

    assert properties["score_status"] == "scored"
    facts = CampsiteFacts.objects.get()
    assert facts.factor_digest == factors_digest()
    assert {entry["key"] for entry in facts.factor_results} >= {"water", "trail", "legal"}
    assert detail("node/1")["score"] == properties["score"]
    assert network.calls == []


def test_a_weight_change_reuses_the_stored_results():
    config = load()
    reweighted = parse(
        {
            "model_version": config.model_version,
            "weights": {**config.weights, "water": config.weights["water"] * 2},
            "factors": config.factors,
        }
    )

    assert factors_digest(reweighted) == factors_digest(config)
