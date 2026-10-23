"""
The roads and sidewalks between trails (TM05-137): pipeline/adapters/osm_connectors.py.
Nothing touches the network.
"""

import pytest

from pipeline.adapters.osm_connectors import OsmConnectorsAdapter, is_walkable_connector
from pipeline.aoi import AreaOfInterest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "tags, walkable",
    [
        ({"highway": "secondary", "name": "Blue Ridge Road"}, True),
        ({"highway": "service", "name": "Branch Road"}, True),
        ({"highway": "residential"}, True),
        ({"highway": "footway", "footway": "sidewalk"}, True),
        ({"highway": "footway", "footway": "crossing"}, True),
        ({"highway": "primary"}, False),
        ({"highway": "motorway"}, False),
        ({"highway": "path"}, False),  # a trail: osm-trails has it
        ({"highway": "footway"}, False),  # a trail footway, likewise
        ({"highway": "residential", "access": "private"}, False),
        ({"highway": "unclassified", "foot": "no"}, False),
        # Fetched; the graph build keeps a driveway only where it meets a trail.
        ({"highway": "service", "service": "driveway"}, True),
        ({"highway": "service", "service": "parking_aisle"}, False),
    ],
)
def test_which_ways_may_be_walked_between_trails(tags, walkable):
    assert is_walkable_connector(tags) is walkable


def test_the_query_asks_for_roads_and_sidewalks_in_the_area():
    adapter = OsmConnectorsAdapter(client=object())
    aoi = AreaOfInterest(name="test", label="Test", bbox=(-74.0, 43.9, -73.8, 44.0))
    query = adapter.build_query(aoi)
    assert "secondary|tertiary|unclassified|residential|living_street|service" in query
    assert '["footway"~"^(sidewalk|crossing)$"]' in query
    assert "out geom;" in query


def test_a_way_becomes_a_connector_record_with_its_node_ids():
    adapter = OsmConnectorsAdapter(client=object())
    way = {
        "type": "way",
        "id": 1394407171,
        "nodes": [212257364, 212039408, 212205679],
        "geometry": [
            {"lon": -73.8370, "lat": 43.9540},
            {"lon": -73.8367, "lat": 43.9544},
            {"lon": -73.8364, "lat": 43.9548},
        ],
        "tags": {"highway": "secondary", "name": "Blue Ridge Road", "ref": "CR 84"},
    }
    record = adapter.to_record(way)
    assert record["source_id"] == "way/1394407171"
    assert (record["name"], record["highway"]) == ("Blue Ridge Road", "secondary")
    assert record["osm_node_ids"] == [212257364, 212039408, 212205679]
    assert record["length_m"] == pytest.approx(103, abs=3)
    unnamed = adapter.to_record({**way, "tags": {"highway": "secondary", "ref": "CR 84"}})
    assert unnamed["name"] == "CR 84"
    assert list(adapter.normalize([[way, {"type": "node", "id": 1}]]))[0]["source_id"] == (
        "way/1394407171"
    )
