"""
Bridging named trails across short unnamed connectors (TM05-98).

Two same-name pieces are joined through unnamed ways that share OSM nodes with both, when
the connectors add up to at most `assembly.connector_max_m` (300 m). Never through a
named way. Ways are straight east-west lines in EPSG:5070, so lengths are exact.
"""

import pytest
from django.contrib.gis.geos import LineString, MultiLineString

from analysis.analyses.elevation import stitch
from geodata.assembly import assembled_route, connected_same_name, connector_max_m
from geodata.models import METRIC_SRID, Trail

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

X0, Y0 = 1_770_000.0, 2_550_000.0
NAME = "Cheney Pond Trail"


def way(number, x0, x1, nodes, name=NAME):
    line = LineString((X0 + x0, Y0), (X0 + x1, Y0), srid=METRIC_SRID)
    return Trail.objects.create(
        source=Trail.Source.OSM,
        source_id=f"way/{number}",
        name=name,
        geom=MultiLineString(line.transform(4326, clone=True), srid=4326),
        length_m=abs(x1 - x0),
        osm_node_ids=nodes,
    )


def ids(members):
    return [member.source_id for member in members]


def test_the_limit_comes_from_routes_yml():
    assert connector_max_m() == 300


def test_a_short_unnamed_connector_bridges_two_same_name_pieces():
    way(1, 0, 1000, [1, 2])
    way(2, 1000, 1080, [2, 3], name="")  # an 80 m bridge, no name
    way(3, 1080, 2500, [3, 4])

    members = connected_same_name(Trail.objects.get(source_id="way/1"))

    assert ids(members) == ["way/1", "way/2", "way/3"]
    line, path = stitch(assembled_route(members[0]).geom)
    assert path["parts_left_out"] == 0
    assert line.length == pytest.approx(2500, abs=1)


def test_a_chain_of_connectors_bridges_while_its_total_is_under_the_limit():
    way(1, 0, 1000, [1, 2])
    way(2, 1000, 1150, [2, 3], name="")
    way(3, 1150, 1290, [3, 4], name="")  # 150 + 140 = 290 m
    way(4, 1290, 2000, [4, 5])
    assert ids(connected_same_name(Trail.objects.get(source_id="way/4"))) == [
        "way/1",
        "way/2",
        "way/3",
        "way/4",
    ]


def test_a_connector_that_is_too_long_is_not_bridged():
    way(1, 0, 1000, [1, 2])
    way(2, 1000, 1400, [2, 3], name="")  # 400 m
    way(3, 1400, 2500, [3, 4])
    assert ids(connected_same_name(Trail.objects.get(source_id="way/1"))) == ["way/1"]


def test_connectors_that_add_up_past_the_limit_are_not_bridged():
    way(1, 0, 1000, [1, 2])
    way(2, 1000, 1200, [2, 3], name="")
    way(3, 1200, 1400, [3, 4], name="")  # 200 + 200 = 400 m
    way(4, 1400, 2500, [4, 5])
    assert ids(connected_same_name(Trail.objects.get(source_id="way/1"))) == ["way/1"]


def test_a_gap_is_never_bridged_through_another_named_trail():
    way(1, 0, 1000, [1, 2])
    way(2, 1000, 1050, [2, 3], name="Short Spur Trail")  # 50 m, but named
    way(3, 1050, 2500, [3, 4])
    members = connected_same_name(Trail.objects.get(source_id="way/1"))
    assert ids(members) == ["way/1"]


def test_an_unnamed_connector_that_reaches_no_same_name_piece_is_left_out():
    way(1, 0, 1000, [1, 2])
    way(2, 1000, 1100, [2, 3], name="")  # a stub to nowhere
    way(3, 1100, 1500, [3, 4], name="Other Trail")
    assert ids(connected_same_name(Trail.objects.get(source_id="way/1"))) == ["way/1"]


def test_bridging_is_the_same_from_either_side():
    way(1, 0, 1000, [1, 2])
    way(2, 1000, 1100, [2, 3], name="")
    way(3, 1100, 2000, [3, 4])
    from_left = ids(connected_same_name(Trail.objects.get(source_id="way/1")))
    from_right = ids(connected_same_name(Trail.objects.get(source_id="way/3")))
    assert from_left == from_right == ["way/1", "way/2", "way/3"]


def test_bridging_can_be_turned_off():
    way(1, 0, 1000, [1, 2])
    way(2, 1000, 1080, [2, 3], name="")
    way(3, 1080, 2500, [3, 4])
    members = connected_same_name(Trail.objects.get(source_id="way/1"), max_connector_m=0)
    assert ids(members) == ["way/1"]
