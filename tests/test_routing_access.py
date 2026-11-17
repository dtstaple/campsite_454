"""
Campsite access difficulty (TM05-171): routing/access.py, plain Python with no database.

The test graph, coordinates in metres:

    H1 (0, 0) --- 1 km flat --- A (1000, 0) --- 6 km, +500 m --- B (7000, 0)
                                                                   |
                                                         1 km flat |
                                                                   |
                                               H2 (7000, 1000) ----+

    L (50000, 50000) -- 1 km -- M (51000, 50000): trails no trailhead joins.
"""

import pytest

from routing.access import (
    EASY,
    HARD,
    MODERATE,
    UNKNOWN,
    classify,
    from_trailheads,
    site_access,
)
from routing.build import config
from routing.engine import Edge, Graph, naismith_seconds

H1, A, B, H2, L, M = 1, 2, 3, 4, 5, 6

SETTINGS = {
    "classes": {
        "easy": {"distance_km": 3, "gain_m": 200, "time_h": 1},
        "moderate": {"distance_km": 10, "gain_m": 600, "time_h": 3.5},
    },
    "trailhead_max_m": 300,
    "campsite_max_m": 500,
}


@pytest.fixture
def graph():
    coords = {
        H1: (0, 0),
        A: (1000, 0),
        B: (7000, 0),
        H2: (7000, 1000),
        L: (50000, 50000),
        M: (51000, 50000),
    }
    return Graph(
        coords,
        [
            Edge(10, H1, A, 1000),
            Edge(11, A, B, 6000, ascent_m=500, descent_m=0),
            Edge(12, H2, B, 1000),
            Edge(13, L, M, 1000),
        ],
    )


def test_config_has_both_limited_classes():
    settings = config()["access"]
    assert set(settings["classes"]) == {"easy", "moderate"}
    for limits in settings["classes"].values():
        assert set(limits) == {"distance_km", "gain_m", "time_h"}


@pytest.mark.parametrize(
    ("distance_m", "gain_m", "expected"),
    [
        (2000, 50, EASY),
        (3000, 200, EASY),  # on every limit is still within it
        (3100, 50, MODERATE),  # past the easy distance
        (2000, 250, MODERATE),  # past the easy climb
        (9000, 500, MODERATE),
        (12000, 100, HARD),  # past the moderate distance
        (8000, 700, HARD),  # past the moderate climb
    ],
)
def test_classes(distance_m, gain_m, expected):
    time_s = naismith_seconds(distance_m, gain_m)
    access = classify(distance_m, gain_m, time_s, "Garden Trailhead", SETTINGS)
    assert access.access_class == expected
    assert "Garden Trailhead" in access.reason
    assert f"{distance_m / 1000:.1f} km" in access.reason


def test_time_alone_can_raise_the_class():
    # 2.9 km flat is about 35 min; a slow road walk recorded at 70 min is not easy.
    access = classify(2900, 0, 70 * 60, "Loj", SETTINGS)
    assert access.access_class == MODERATE


def test_reason_is_one_line():
    access = classify(12000, 100, naismith_seconds(12000, 100), "Loj", SETTINGS)
    assert "\n" not in access.reason
    assert "over the moderate limit" in access.reason


def test_quickest_trailhead_wins(graph):
    reach = from_trailheads(graph, {H1: "West", H2: "East"})
    # B: from H2 is 1 km flat; from H1 is 7 km with 500 m of climb.
    assert reach[B].trailhead == "East"
    assert reach[B].length_m == 1000
    # A: from H1 is 1 km; from H2 is 7 km downhill.
    assert reach[A].trailhead == "West"


def test_climb_is_counted_in_the_walking_direction(graph):
    reach = from_trailheads(graph, {H1: "West"})
    assert reach[B].length_m == 7000
    assert reach[B].ascent_m == 500
    reach = from_trailheads(graph, {H2: "East"})
    assert reach[A].ascent_m == 0  # B -> A is the descent


def test_unreachable_nodes_are_absent(graph):
    reach = from_trailheads(graph, {H1: "West", H2: "East"})
    assert L not in reach and M not in reach


def test_unreachable_site_is_unknown_never_guessed(graph):
    reach = from_trailheads(graph, {H1: "West"})
    access = site_access(reach.get(L), 20.0, SETTINGS)
    assert access.access_class == UNKNOWN
    assert access.distance_m is None and access.time_s is None
    assert "No trailhead connects" in access.reason


def test_site_far_from_any_trail_is_unknown():
    access = site_access(None, None, SETTINGS)
    assert access.access_class == UNKNOWN
    assert "500 m" in access.reason


def test_site_adds_its_approach_as_flat_walking(graph):
    reach = from_trailheads(graph, {H1: "West"})
    access = site_access(reach[A], 200.0, SETTINGS)
    assert access.distance_m == 1200
    assert access.gain_m == 0
    assert access.time_s == pytest.approx(naismith_seconds(1200, 0))
    assert access.access_class == EASY


def test_trailhead_not_on_graph_is_ignored(graph):
    reach = from_trailheads(graph, {999: "Nowhere", H1: "West"})
    assert all(r.trailhead == "West" for r in reach.values())
