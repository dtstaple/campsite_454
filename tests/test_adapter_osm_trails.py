"""
OSM trails adapter tests.

Fixtures in `tests/fixtures/osm_trails_page.json` were recorded from a real Overpass
`out geom` response over the High Peaks, trimmed to eight ways that between them cover
all four highway values, named and unnamed, and one 444-node way (the Northville-Placid
Trail) so node ordering is exercised on something realistic rather than a toy.

This is also the first real exercise of the framework's tiling, so the tiling behaviour
is under test here as much as the adapter is.

The one test that touches the network is marked `network` and deselected by default.
"""

import json
import pathlib
from unittest.mock import Mock, patch

import pytest
import requests

from geodata.models import IngestRun, Trail
from pipeline.adapters.osm_trails import TRAIL_HIGHWAY_VALUES, OsmTrailsAdapter
from pipeline.aoi import AreaOfInterest
from pipeline.geometry import geodesic_length_m
from pipeline.overpass import (
    OverpassClient,
    OverpassResponseError,
    OverpassUnavailable,
)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "osm_trails_page.json"

# Full park: 2.1 x 1.9 degrees, so max_tile_degrees=1.0 gives a 3 x 2 grid.
ADK = AreaOfInterest(
    name="adirondacks",
    label="Adirondack Park",
    bbox=(-75.40, 43.00, -73.30, 44.90),
    states=("NY",),
)

# A deliberately tiny slice for the live test -- one small valley, not the park.
TINY = AreaOfInterest(
    name="adk-tiny",
    label="Adirondack test slice",
    bbox=(-74.10, 44.10, -74.05, 44.15),
    states=("NY",),
)


@pytest.fixture
def elements():
    return json.loads(FIXTURE.read_text())["elements"]


def stub_client(pages):
    """An OverpassClient replacement returning a prepared payload per call."""
    client = Mock(spec=OverpassClient)
    client.endpoint = "https://stub.invalid/api/interpreter"
    client.query = Mock(side_effect=[{"elements": page} for page in pages])
    return client


def adapter_for(pages):
    return OsmTrailsAdapter(client=stub_client(pages))


def way_named(elements, name):
    return next(w for w in elements if w["tags"].get("name") == name)


# --- fixture integrity ----------------------------------------------------------------


@pytest.mark.unit
def test_the_fixture_covers_every_highway_value(elements):
    assert {w["tags"]["highway"] for w in elements} == set(TRAIL_HIGHWAY_VALUES)
    assert any(not w["tags"].get("name") for w in elements), "need an unnamed way"
    assert max(len(w["nodes"]) for w in elements) > 100, "need a realistically long way"


# --- node IDs: the whole point of this adapter ----------------------------------------


@pytest.mark.unit
def test_node_ids_are_stored_in_order_not_as_a_set(elements):
    long_way = way_named(elements, "Northville-Placid Trail")
    record = adapter_for([]).to_record(long_way)

    assert record["osm_node_ids"] == long_way["nodes"], "order must be preserved exactly"
    assert isinstance(record["osm_node_ids"], list), "a set would destroy ordering"
    assert len(record["osm_node_ids"]) == 444


@pytest.mark.unit
def test_node_ids_line_up_one_to_one_with_coordinates(elements):
    """`out geom` returns both arrays; they must stay in step."""
    for way in elements:
        record = adapter_for([]).to_record(way)
        assert len(record["osm_node_ids"]) == len(way["geometry"])
        assert len(record["geom"].coords) == len(way["geometry"])


@pytest.mark.unit
def test_a_shared_node_is_visible_across_two_ways():
    """What makes a routing graph possible later: junctions share a node ID."""
    first = {
        "type": "way",
        "id": 1,
        "tags": {"highway": "path"},
        "nodes": [10, 11, 12],
        "geometry": [
            {"lon": -74.0, "lat": 44.0},
            {"lon": -74.0, "lat": 44.01},
            {"lon": -74.0, "lat": 44.02},
        ],
    }
    second = {
        "type": "way",
        "id": 2,
        "tags": {"highway": "path"},
        "nodes": [12, 13],
        "geometry": [{"lon": -74.0, "lat": 44.02}, {"lon": -74.01, "lat": 44.02}],
    }

    adapter = adapter_for([])
    a = adapter.to_record(first)["osm_node_ids"]
    b = adapter.to_record(second)["osm_node_ids"]

    assert a[-1] == b[0] == 12, "the junction node must survive in both ways"


# --- field mapping --------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("highway", TRAIL_HIGHWAY_VALUES)
def test_every_highway_value_maps_to_trail_type(elements, highway):
    way = next(w for w in elements if w["tags"]["highway"] == highway)

    assert adapter_for([]).to_record(way)["trail_type"] == highway


@pytest.mark.unit
def test_a_way_with_no_name_gets_an_empty_string_not_none(elements):
    unnamed = next(w for w in elements if not w["tags"].get("name"))

    record = adapter_for([]).to_record(unnamed)

    assert record["name"] == "", "the model field is blank=True, not null=True"


@pytest.mark.unit
def test_source_id_uses_the_stable_osm_way_id(elements):
    way = elements[0]

    record = adapter_for([]).to_record(way)

    assert record["source_id"] == f"way/{way['id']}"
    # Unlike PAD-US, nothing is synthesized -- the same input always gives the same ID
    # because OSM assigns it.
    assert adapter_for([]).to_record(way)["source_id"] == record["source_id"]


@pytest.mark.unit
def test_tags_are_preserved_in_raw(elements):
    way = way_named(elements, "Northville-Placid Trail")

    record = adapter_for([]).to_record(way)

    assert record["raw"]["tags"] == way["tags"]
    assert record["raw"]["id"] == way["id"]


@pytest.mark.unit
def test_normalize_leaves_linestring_coercion_to_the_framework(elements):
    record = adapter_for([]).to_record(elements[0])

    assert record["geom"].geom_type == "LineString", "the base class promotes, not us"


@pytest.mark.unit
def test_normalize_skips_non_way_elements(elements):
    noise = [{"type": "node", "id": 9, "lat": 44.0, "lon": -74.0}] + elements

    records = list(adapter_for([]).normalize([noise]))

    assert len(records) == len(elements)


# --- length -----------------------------------------------------------------------------


@pytest.mark.unit
def test_length_is_computed_in_metres_not_degrees(elements):
    long_way = way_named(elements, "Northville-Placid Trail")

    record = adapter_for([]).to_record(long_way)

    # A degrees-based .length would be a number below 1. Real metres are in the
    # thousands for a way this size.
    assert record["length_m"] > 1000
    assert record["geom"].length < 1, "sanity: the raw geometry really is in degrees"


@pytest.mark.unit
def test_length_matches_an_independent_calculation(elements):
    way = elements[0]
    coordinates = [(p["lon"], p["lat"]) for p in way["geometry"]]

    assert adapter_for([]).to_record(way)["length_m"] == pytest.approx(
        geodesic_length_m(coordinates)
    )


@pytest.mark.unit
def test_a_one_point_way_has_no_geometry_and_is_left_for_the_framework_to_skip():
    degenerate = {
        "type": "way",
        "id": 7,
        "tags": {"highway": "path"},
        "nodes": [1],
        "geometry": [{"lon": -74.0, "lat": 44.0}],
    }

    record = adapter_for([]).to_record(degenerate)

    assert record["geom"] is None
    assert record["source_id"] == "way/7"


@pytest.mark.unit
def test_geodesic_length_of_a_known_distance():
    """One degree of latitude is close to 111 km anywhere on Earth."""
    metres = geodesic_length_m([(-74.0, 44.0), (-74.0, 45.0)])

    assert metres == pytest.approx(111_195, rel=0.001)


# --- the query -------------------------------------------------------------------------


@pytest.mark.unit
def test_the_query_asks_for_out_geom_over_the_right_bbox():
    adapter = adapter_for([])

    query = adapter.build_query(TINY)

    assert "out geom;" in query, "out body would omit coordinates"
    # Overpass wants (min_lat, min_lon, max_lat, max_lon), not bbox order.
    assert "(44.1,-74.1,44.15,-74.05)" in query
    assert 'way["highway"~"^(path|footway|track|bridleway)$"]' in query
    assert "[out:json]" in query


# --- tiling: first real exercise of the framework feature ------------------------------


@pytest.mark.django_db
@pytest.mark.integration
def test_the_adirondacks_are_split_into_multiple_tiles(elements):
    client = stub_client([[] for _ in range(6)])
    adapter = OsmTrailsAdapter(client=client)

    adapter.run(ADK)

    assert client.query.call_count == 6, "2.1 x 1.9 degrees at 1.0 should be a 3 x 2 grid"
    bboxes = {call.args[0] for call in client.query.call_args_list}
    assert len(bboxes) == 6, "each tile must query a distinct area"


@pytest.mark.django_db
@pytest.mark.integration
def test_a_way_returned_by_two_tiles_becomes_one_row(elements):
    """A trail crossing a tile boundary comes back from both tiles."""
    shared = [elements[0]]
    client = stub_client([shared] * 6)
    adapter = OsmTrailsAdapter(client=client)

    run = adapter.run(ADK)

    assert Trail.objects.count() == 1, "cross-tile dedup should collapse the repeats"
    assert run.record_count == 1
    assert run.status == IngestRun.Status.SUCCESS


@pytest.mark.django_db
@pytest.mark.integration
def test_distinct_ways_from_different_tiles_all_land(elements):
    pages = [[way] for way in elements[:6]]
    adapter = OsmTrailsAdapter(client=stub_client(pages))

    run = adapter.run(ADK)

    assert Trail.objects.count() == 6
    assert run.record_count == 6


# --- end to end against the database ----------------------------------------------------


@pytest.mark.django_db
@pytest.mark.integration
def test_rows_land_with_promoted_geometry_and_node_ids(elements):
    adapter = OsmTrailsAdapter(client=stub_client([elements] + [[]] * 5))

    run = adapter.run(ADK)

    assert run.record_count == len(elements)
    assert Trail.objects.count() == len(elements)

    for trail in Trail.objects.all():
        assert trail.geom.srid == 4326
        assert trail.geom.geom_type == "MultiLineString", "framework promotes LineString"
        assert trail.osm_node_ids, "node IDs are the reason this adapter exists"
        assert trail.length_m > 0
        assert trail.source == Trail.Source.OSM
        assert trail.last_run_id == run.pk

    stored = Trail.objects.get(source_id="way/20089285")
    assert stored.name == "Northville-Placid Trail"
    assert stored.osm_node_ids == way_named(elements, "Northville-Placid Trail")["nodes"]


@pytest.mark.django_db
@pytest.mark.integration
def test_running_twice_is_idempotent(elements):
    first = OsmTrailsAdapter(client=stub_client([elements] + [[]] * 5)).run(ADK)
    second = OsmTrailsAdapter(client=stub_client([elements] + [[]] * 5)).run(ADK)

    assert Trail.objects.count() == len(elements), "a rerun must update, not duplicate"
    assert IngestRun.objects.count() == 2
    assert first.pk != second.pk
    assert all(t.last_run_id == second.pk for t in Trail.objects.all())


# --- Overpass client error handling ------------------------------------------------------


def http_response(status=200, body=None, text=None):
    response = Mock(spec=requests.Response)
    response.status_code = status
    response.text = text if text is not None else json.dumps(body)
    if body is None:
        response.json = Mock(side_effect=ValueError("not json"))
    else:
        response.json = Mock(return_value=body)
    return response


def client_with(responses, **kwargs):
    kwargs.setdefault("sleep", lambda _: None)  # never actually wait in tests
    client = OverpassClient(**kwargs)
    return client, patch.object(requests.Session, "post", side_effect=responses)


@pytest.mark.unit
def test_a_406_says_it_is_about_the_user_agent_and_does_not_retry():
    client, patcher = client_with([http_response(406, text="Not Acceptable")])

    with patcher as post:
        with pytest.raises(OverpassResponseError) as err:
            client.query("out count;")

    message = str(err.value)
    assert "406" in message
    assert "User-Agent" in message
    assert "Retrying will not help" in message
    assert post.call_count == 1, "a 406 is permanent; retrying wastes the rate limit"


@pytest.mark.unit
def test_a_non_json_body_is_treated_as_overload_and_reported_clearly():
    html = "<html><head><title>504 Gateway Timeout</title></head></html>"
    client, patcher = client_with([http_response(200, text=html)] * 4, max_attempts=4)

    with patcher:
        with pytest.raises(OverpassUnavailable) as err:
            client.query("out count;")

    message = str(err.value)
    assert "non-JSON" in message or "still unavailable" in message
    assert "2 concurrent slots" in message


@pytest.mark.unit
def test_rate_limiting_is_retried_then_succeeds():
    responses = [
        http_response(429, text="rate_limited"),
        http_response(200, body={"elements": [{"type": "way", "id": 1}]}),
    ]
    client, patcher = client_with(responses)

    with patcher as post:
        payload = client.query("out count;")

    assert post.call_count == 2, "the 429 should have been retried"
    assert payload["elements"][0]["id"] == 1


@pytest.mark.unit
def test_backoff_grows_between_attempts():
    delays = []
    client, patcher = client_with(
        [http_response(429, text="busy")] * 3,
        max_attempts=3,
        backoff_seconds=2.0,
        sleep=delays.append,
    )

    with patcher:
        with pytest.raises(OverpassUnavailable):
            client.query("out count;")

    assert delays == [2.0, 4.0], "exponential, not a flat retry"


@pytest.mark.unit
def test_a_connection_failure_is_wrapped_and_retried():
    client = OverpassClient(sleep=lambda _: None, max_attempts=2)

    with patch.object(requests.Session, "post", side_effect=requests.ConnectionError("dns")):
        with pytest.raises(OverpassUnavailable, match="still unavailable"):
            client.query("out count;")


@pytest.mark.unit
def test_a_response_without_elements_is_a_permanent_error():
    client, patcher = client_with([http_response(200, body={"version": 0.6})])

    with patcher:
        with pytest.raises(OverpassResponseError, match="no 'elements' key"):
            client.query("out count;")


@pytest.mark.unit
def test_the_user_agent_is_actually_sent():
    client = OverpassClient()

    assert "CampSite" in client._session.headers["User-Agent"]
    assert client._session.headers["User-Agent"] == client.user_agent


# --- the one test that hits the live service ---------------------------------------------


@pytest.mark.network
@pytest.mark.django_db
@pytest.mark.integration
def test_live_overpass_returns_usable_trails():
    """Hits Overpass for real over a tiny bbox. Run with: pytest -m network

    Deliberately a single small valley rather than the park: Overpass is a free service
    with two shared slots and this runs on every explicit network test invocation.
    """
    run = OsmTrailsAdapter().run(TINY)

    assert run.status in {IngestRun.Status.SUCCESS, IngestRun.Status.PARTIAL}
    assert run.record_count > 0
    assert Trail.objects.count() == run.record_count

    for trail in Trail.objects.all()[:20]:
        assert trail.geom.srid == 4326
        assert trail.geom.geom_type == "MultiLineString"
        assert trail.geom.valid, trail.geom.valid_reason
        assert trail.source_id.startswith("way/")
        assert len(trail.osm_node_ids) >= 2
        assert all(isinstance(n, int) for n in trail.osm_node_ids)
        assert trail.length_m > 0
        assert trail.trail_type in TRAIL_HIGHWAY_VALUES
