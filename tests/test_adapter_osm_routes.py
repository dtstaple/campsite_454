"""
OSM routes adapter tests (TM05-58).

`tests/fixtures/osm_routes_page.json` was recorded from a live Overpass
`relation["route"="hiking"](adirondacks); out geom;` response on 2026-10-02 and trimmed to
four relations chosen for what they exercise:

- Van Hoevenberg Trail (6619234): 32 ordered way members, the calibration route
- Western Ridge Trail (12343312): has a `connection` side branch
- Rocky Mountain Trail (20254765): no way members at all, so it has no geometry
- Easy Street (5353713): lists one way twice

No test touches the network.
"""

import json
import pathlib
from unittest.mock import Mock

import pytest

from geodata.models import IngestRun, TrailRoute
from pipeline.adapters.osm_routes import SIDE_BRANCH_ROLES, OsmRoutesAdapter
from pipeline.aoi import AreaOfInterest
from pipeline.geometry import geodesic_length_m
from pipeline.overpass import OverpassClient

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "osm_routes_page.json"

ADK = AreaOfInterest(
    name="adirondacks",
    label="Adirondack Park",
    bbox=(-75.40, 43.00, -73.30, 44.90),
    states=("NY",),
)


@pytest.fixture
def elements():
    return json.loads(FIXTURE.read_text())["elements"]


def by_id(elements, osm_id):
    return next(e for e in elements if e["id"] == osm_id)


def adapter_for(pages):
    client = Mock(spec=OverpassClient)
    client.endpoint = "https://stub.invalid/api/interpreter"
    client.query = Mock(side_effect=[{"elements": page} for page in pages])
    return OsmRoutesAdapter(client=client)


# --- mapping (no database) -------------------------------------------------------------


@pytest.mark.unit
def test_query_asks_for_hiking_relations_with_geometry():
    query = adapter_for([]).build_query(ADK)
    assert 'relation["route"="hiking"]' in query
    assert "out geom" in query
    assert "43.0,-75.4,44.9,-73.3" in query


@pytest.mark.unit
def test_route_keeps_name_relation_id_and_ordered_members(elements):
    relation = by_id(elements, 6619234)
    record = adapter_for([]).to_record(relation)

    assert record["source_id"] == "relation/6619234"
    assert record["osm_id"] == 6619234
    assert record["name"] == "Van Hoevenberg Trail"
    assert record["member_way_ids"] == [m["ref"] for m in relation["members"]]
    assert len(record["member_way_ids"]) == 32
    # One line per member, in relation order.
    assert len(record["geom"]) == 32
    first = relation["members"][0]["geometry"][0]
    assert record["geom"][0].coords[0] == (first["lon"], first["lat"])


@pytest.mark.unit
def test_length_is_the_geodesic_sum_of_members(elements):
    relation = by_id(elements, 6619234)
    record = adapter_for([]).to_record(relation)
    expected = sum(
        geodesic_length_m([(p["lon"], p["lat"]) for p in m["geometry"]])
        for m in relation["members"]
    )
    assert record["length_m"] == pytest.approx(expected)
    # Published one-way length to the summit is ~7.4 mi; the relation runs a little
    # further, so it should be in that neighbourhood, not wildly off.
    assert 6.5 < record["length_m"] / 1609.344 < 8.5


@pytest.mark.unit
def test_side_branches_stay_members_but_not_length(elements):
    relation = by_id(elements, 12343312)
    record = adapter_for([]).to_record(relation)
    branches = [m for m in relation["members"] if m.get("role") in SIDE_BRANCH_ROLES]

    assert branches, "fixture should include a side branch"
    assert all(m["ref"] in record["member_way_ids"] for m in branches)
    assert len(record["geom"]) == len(relation["members"]) - len(branches)


@pytest.mark.unit
def test_a_way_listed_twice_counts_once(elements):
    relation = by_id(elements, 5353713)
    refs = [m["ref"] for m in relation["members"] if m["type"] == "way"]
    assert len(refs) != len(set(refs)), "fixture should repeat a way"

    record = adapter_for([]).to_record(relation)
    assert record["member_way_ids"] == refs
    assert len(record["geom"]) == len(set(refs))


@pytest.mark.unit
def test_relation_without_way_members_has_no_geometry(elements):
    record = adapter_for([]).to_record(by_id(elements, 20254765))
    assert record["geom"] is None
    assert record["member_way_ids"] == []


@pytest.mark.unit
def test_non_relations_are_ignored(elements):
    page = elements + [{"type": "way", "id": 1, "tags": {}}]
    records = list(adapter_for([]).normalize([page]))
    assert len(records) == len(elements)


@pytest.mark.unit
def test_one_query_per_region_not_per_tile():
    adapter = adapter_for([])
    assert len(list(adapter.iter_areas(ADK))) == 1


# --- end to end (database) -------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.integration
def test_run_loads_routes_and_skips_the_geometryless_one(elements):
    run = adapter_for([elements]).run(ADK)

    assert run.status == IngestRun.Status.PARTIAL
    assert run.record_count == 3
    assert "relation/20254765" in run.notes
    route = TrailRoute.objects.get(osm_id=6619234)
    assert route.geom.srid == 4326
    assert route.geom_m.srid == 5070
    assert route.last_run == run
    assert run.parameters["side_branch_roles"] == sorted(SIDE_BRANCH_ROLES)


@pytest.mark.django_db
@pytest.mark.integration
def test_rerun_upserts_instead_of_duplicating(elements):
    adapter_for([elements]).run(ADK)
    renamed = json.loads(json.dumps(elements))
    by_id(renamed, 6619234)["tags"]["name"] = "Van Hoevenberg Trail (renamed)"
    adapter_for([renamed]).run(ADK)

    assert TrailRoute.objects.count() == 3
    assert TrailRoute.objects.get(osm_id=6619234).name == "Van Hoevenberg Trail (renamed)"
