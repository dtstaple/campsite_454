"""
OSM campsites adapter tests.

`tests/fixtures/osm_campsites_page.json` was recorded from a real Overpass `out center`
response over the High Peaks, trimmed to nine elements chosen to cover the cases that
differ: backcountry nodes named and unnamed, non-backcountry nodes, ways (which carry a
`center` rather than a `lat`/`lon`), and one relation, which must not be ingested.

The one test that touches the network is marked `network` and deselected by default.
"""

import json
import pathlib
from unittest.mock import Mock, patch

import pytest

from geodata.models import Campsite, IngestRun
from pipeline.adapters.osm_campsites import (
    CAMPSITE_ELEMENT_TYPES,
    OsmCampsitesAdapter,
)
from pipeline.aoi import AreaOfInterest
from pipeline.overpass import OverpassClient

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "osm_campsites_page.json"

# Full park: 2.1 x 1.9 degrees, so max_tile_degrees=2.0 gives a 2 x 1 grid.
ADK = AreaOfInterest(
    name="adirondacks",
    label="Adirondack Park",
    bbox=(-75.40, 43.00, -73.30, 44.90),
    states=("NY",),
)

# A deliberately tiny slice for the live test -- one valley, not the park.
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
    return OsmCampsitesAdapter(client=stub_client(pages))


def element_of_type(elements, kind):
    return next(e for e in elements if e["type"] == kind)


# --- the query --------------------------------------------------------------------------


def test_the_query_asks_for_nodes_and_ways_over_the_right_bbox():
    adapter = adapter_for([])

    query = adapter.build_query(TINY)

    assert 'node["tourism"="camp_site"]' in query
    assert 'way["tourism"="camp_site"]' in query
    # Overpass wants (min_lat, min_lon, max_lat, max_lon), not bbox order.
    assert "(44.1,-74.1,44.15,-74.05)" in query
    assert "[out:json]" in query


def test_the_query_asks_for_out_center_so_a_way_resolves_to_one_point():
    adapter = adapter_for([])

    assert "out center;" in adapter.build_query(TINY)


def test_relations_are_never_requested():
    """Skipping them at the query means they are not transferred at all."""
    adapter = adapter_for([])

    assert 'relation["tourism"="camp_site"]' not in adapter.build_query(TINY)
    assert "relation" not in CAMPSITE_ELEMENT_TYPES


# --- normalisation ----------------------------------------------------------------------


def test_a_node_becomes_a_point_at_its_own_coordinates(elements):
    node = element_of_type(elements, "node")
    adapter = adapter_for([])

    record = adapter.to_record(node)

    assert record["geom"].srid == 4326
    assert record["geom"].x == pytest.approx(node["lon"])
    assert record["geom"].y == pytest.approx(node["lat"])


def test_a_way_becomes_a_point_at_its_center(elements):
    """A way is an area you pitch inside; the model stores one spot."""
    way = element_of_type(elements, "way")
    adapter = adapter_for([])

    record = adapter.to_record(way)

    assert record["geom"].x == pytest.approx(way["center"]["lon"])
    assert record["geom"].y == pytest.approx(way["center"]["lat"])


def test_both_nodes_and_ways_are_normalised(elements):
    adapter = adapter_for([])

    records = list(adapter.normalize([elements]))
    kinds = {record["source_id"].split("/")[0] for record in records}

    assert kinds == {"node", "way"}, "both element types must survive normalisation"


def test_a_relation_in_the_response_is_not_normalised(elements):
    """Belt and braces: the query excludes them, and so does normalize."""
    adapter = adapter_for([])

    records = list(adapter.normalize([elements]))

    assert any(e["type"] == "relation" for e in elements), "fixture must contain a relation"
    assert not any(record["source_id"].startswith("relation/") for record in records)


def test_source_id_is_prefixed_with_the_element_type(elements):
    adapter = adapter_for([])
    node = element_of_type(elements, "node")

    assert adapter.to_record(node)["source_id"] == f"node/{node['id']}"


def test_source_ids_cannot_collide_with_ridb_campsites(elements):
    """Both sources write into one table and the save endpoint resolves on source_id
    alone, so the namespaces have to stay disjoint."""
    adapter = adapter_for([])

    for record in adapter.normalize([elements]):
        assert not record["source_id"].startswith("campsite/")


def test_an_element_with_no_location_is_left_for_the_framework_to_skip():
    adapter = adapter_for([])
    homeless = {"type": "way", "id": 1, "tags": {"tourism": "camp_site"}}

    assert adapter.to_record(homeless)["geom"] is None


def test_tags_are_preserved_in_raw(elements):
    adapter = adapter_for([])
    node = element_of_type(elements, "node")

    record = adapter.to_record(node)

    assert record["raw"]["tags"] == node["tags"]
    assert record["raw"]["type"] == "node"


# --- site type --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"backcountry": "yes"}, Campsite.SiteType.PRIMITIVE),
        ({"group_only": "yes"}, Campsite.SiteType.GROUP),
        ({"shelter_type": "lean_to"}, Campsite.SiteType.LEAN_TO),
        # The residual. tourism=camp_site alone says somebody mapped a camping spot,
        # not that it is a developed campground, so it must not become "designated".
        ({}, Campsite.SiteType.UNKNOWN),
        ({"backcountry": "no"}, Campsite.SiteType.UNKNOWN),
        ({"camp_site": "basic"}, Campsite.SiteType.UNKNOWN),
    ],
)
def test_site_type_is_mapped_only_where_the_tag_is_unambiguous(tags, expected):
    assert OsmCampsitesAdapter.map_site_type(tags) == expected


def test_the_more_specific_rule_wins_over_backcountry():
    tags = {"backcountry": "yes", "shelter_type": "lean_to"}

    assert OsmCampsitesAdapter.map_site_type(tags) == Campsite.SiteType.LEAN_TO


def test_backcountry_sites_are_the_ones_this_project_is_about(elements):
    """153 of 230 sampled High Peaks campsites carry backcountry=yes."""
    adapter = adapter_for([])

    records = list(adapter.normalize([elements]))
    primitive = [r for r in records if r["site_type"] == Campsite.SiteType.PRIMITIVE]

    assert primitive, "the fixture should contain backcountry sites"


# --- tri-state fields -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("required", True), ("yes", True), ("no", False), ("not_possible", False)],
)
def test_reservation_maps_to_reservable(value, expected):
    assert OsmCampsitesAdapter.map_reservable({"reservation": value}) is expected


def test_a_missing_reservation_tag_stays_null_not_false():
    """null means "not recorded", which is not the same as "no"."""
    assert OsmCampsitesAdapter.map_reservable({}) is None
    assert OsmCampsitesAdapter.map_reservable({"reservation": "sometimes"}) is None


def test_capacity_is_parsed_when_numeric():
    assert OsmCampsitesAdapter.map_capacity({"capacity": "54"}) == 54


@pytest.mark.parametrize("value", ["", "lots", "6-8", "-3", "0", "99999"])
def test_capacity_that_is_not_a_usable_number_stays_null(value):
    """OSM capacity is free text. A value that would overflow the column or that cannot
    be read is left null rather than coerced -- guessing would assert a number nobody
    published, and an out-of-range one would take the whole batch down on save."""
    assert OsmCampsitesAdapter.map_capacity({"capacity": value}) is None


# --- loading ----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.integration
def test_rows_land_with_geometry_and_provenance(elements):
    adapter = adapter_for([elements, []])

    run = adapter.run(ADK)

    assert Campsite.objects.filter(source=Campsite.Source.OSM).exists()
    assert run.record_count == Campsite.objects.filter(source=Campsite.Source.OSM).count()
    for campsite in Campsite.objects.filter(source=Campsite.Source.OSM):
        assert campsite.geom.srid == 4326
        assert campsite.last_run_id == run.id


@pytest.mark.django_db
@pytest.mark.integration
def test_rerunning_upserts_rather_than_duplicating(elements):
    first = adapter_for([elements, []]).run(ADK)
    after_first = Campsite.objects.filter(source=Campsite.Source.OSM).count()

    second = adapter_for([elements, []]).run(ADK)

    assert Campsite.objects.filter(source=Campsite.Source.OSM).count() == after_first
    assert first.id != second.id, "each run gets its own provenance row"
    assert IngestRun.objects.filter(source=Campsite.Source.OSM).count() == 2
    # Every row now points at the newer run.
    assert not Campsite.objects.filter(source=Campsite.Source.OSM, last_run_id=first.id).exists()


@pytest.mark.django_db
@pytest.mark.integration
def test_osm_campsites_do_not_disturb_ridb_campsites(elements):
    """Two sources, one table. Loading one must not touch the other's rows."""
    from django.contrib.gis.geos import Point

    ridb = Campsite.objects.create(
        source=Campsite.Source.RIDB,
        source_id="campsite/73996",
        name="Russell Pond",
        geom=Point(-71.3, 44.1, srid=4326),
    )

    adapter_for([elements, []]).run(ADK)

    ridb.refresh_from_db()
    assert ridb.name == "Russell Pond"
    assert Campsite.objects.filter(source=Campsite.Source.RIDB).count() == 1


@pytest.mark.django_db
@pytest.mark.integration
def test_run_parameters_record_what_was_asked_for(elements):
    run = adapter_for([elements, []]).run(ADK)

    assert run.parameters["element_types"] == ["node", "way"]
    assert run.parameters["tourism_value"] == "camp_site"
    assert run.region == "adirondacks"


# --- live -------------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.django_db
@pytest.mark.integration
def test_a_small_real_area_loads_from_overpass():
    """Hits the public Overpass instance over one small Adirondack slice.

    Asserts shape rather than an exact count, because OSM is edited continuously and
    pinning a number here would make the test fail on somebody else's mapping work.
    """
    run = OsmCampsitesAdapter().run(TINY)

    assert run.status in {IngestRun.Status.SUCCESS, IngestRun.Status.PARTIAL}
    loaded = Campsite.objects.filter(source=Campsite.Source.OSM)
    assert loaded.exists(), "the High Peaks slice should contain campsites"
    for campsite in loaded:
        assert campsite.geom.srid == 4326
        west, south, east, north = TINY.bbox
        assert west <= campsite.geom.x <= east
        assert south <= campsite.geom.y <= north
        assert campsite.source_id.split("/")[0] in CAMPSITE_ELEMENT_TYPES


@pytest.mark.django_db
@pytest.mark.integration
def test_a_failing_overpass_call_records_a_failed_run_and_re_raises():
    """The caller still sees the error; the provenance row explains it afterwards."""
    client = Mock(spec=OverpassClient)
    client.endpoint = "https://stub.invalid/api/interpreter"
    client.query = Mock(side_effect=RuntimeError("Overpass is having a day"))

    with patch.object(OsmCampsitesAdapter, "max_tile_degrees", 10.0):
        with pytest.raises(RuntimeError, match="Overpass is having a day"):
            OsmCampsitesAdapter(client=client).run(ADK)

    run = IngestRun.objects.filter(source=Campsite.Source.OSM).latest("started_at")
    assert run.status == IngestRun.Status.FAILED
    assert "Overpass is having a day" in run.notes
    assert run.record_count == 0
