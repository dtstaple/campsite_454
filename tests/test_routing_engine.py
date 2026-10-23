"""
The routing engine (TM05-119): routing/engine.py, plain Python with no database. These
are the cases any replacement engine (docs/routing.md) has to pass too.

The test graph, coordinates in metres:

        T (0, 2000) ----------- steep: +600 m ---------- A (0, 0)
        |                                                 |
    flat 3 km                                         flat 1 km
        |                                                 |
        F (3000, 2000) --------- flat 2 km -------------- B (1000, 0)

    A -> T directly is 2 km with 600 m of climb; A -> B -> F -> T is 6 km and flat.
    I (9000, 9000) is on its own.
"""

import pytest

from routing.engine import (
    Edge,
    Graph,
    NoRoute,
    RoutingError,
    naismith_seconds,
    route,
)

pytestmark = pytest.mark.unit

A, B, F, T, I = 1, 2, 3, 4, 5  # noqa: E741 -- the island node
COORDS = {A: (0, 0), B: (1000, 0), F: (3000, 2000), T: (0, 2000), I: (9000, 9000)}


def graph():
    return Graph(
        COORDS,
        [
            Edge(10, A, T, 2000, ascent_m=600, descent_m=0),
            Edge(11, A, B, 1000),
            Edge(12, B, F, 2000),
            Edge(13, F, T, 3000),
        ],
    )


def test_naismith_is_5_km_an_hour_plus_an_hour_per_600_m():
    assert naismith_seconds(5000, 0) == pytest.approx(3600)
    assert naismith_seconds(5000, 600) == pytest.approx(7200)


def test_distance_takes_the_short_steep_way():
    found = route(graph(), A, T, cost="distance")
    assert found.nodes == [A, T]
    assert found.length_m == 2000
    assert found.ascent_m == 600


def test_naismith_takes_the_long_flat_way_when_it_is_quicker():
    # Steep: 2 km + 600 m = 24 + 60 = 84 min. Flat: 6 km = 72 min.
    found = route(graph(), A, T, cost="naismith")
    assert found.nodes == [A, B, F, T]
    assert found.length_m == 6000
    assert found.naismith_s == pytest.approx(72 * 60)


def test_walking_an_edge_backwards_swaps_ascent_and_descent():
    found = route(graph(), T, A, cost="distance")
    assert found.nodes == [T, A]
    assert (found.ascent_m, found.descent_m) == (0, 600)
    step = found.steps[0]
    assert (step.edge, step.forward, step.from_node, step.to_node) == (10, False, T, A)


def test_downhill_is_free_so_naismith_goes_straight_down():
    assert route(graph(), T, A, cost="naismith").nodes == [T, A]


def test_waypoints_are_visited_in_the_order_given():
    there = route(graph(), A, T, waypoints=[F], cost="distance")
    assert there.nodes == [A, B, F, T]
    assert [(leg.start, leg.end) for leg in there.legs] == [(A, F), (F, T)]
    out_and_back = route(graph(), A, A, waypoints=[T, B], cost="distance")
    assert out_and_back.nodes == [A, T, A, B, A]
    assert out_and_back.length_m == 2000 + 2000 + 1000 + 1000


def test_an_unconnected_destination_raises_no_route():
    with pytest.raises(NoRoute) as caught:
        route(graph(), A, I)
    assert (caught.value.start, caught.value.end) == (A, I)


def test_unknown_nodes_and_costs_are_errors():
    with pytest.raises(RoutingError, match="not on the trail graph"):
        route(graph(), A, 99)
    with pytest.raises(RoutingError, match="Unknown cost"):
        route(graph(), A, T, cost="scenic")


def test_a_leg_from_a_node_to_itself_is_empty():
    found = route(graph(), A, A)
    assert found.steps == [] and found.length_m == 0


def test_a_copy_takes_new_nodes_without_changing_the_original():
    base = graph()
    twin = base.copy()
    twin.add_node(6, (500, 0))
    twin.remove_edge(11)
    twin.add_edge(Edge(-1, A, 6, 500))
    twin.add_edge(Edge(-2, 6, B, 500))
    assert route(twin, A, B, cost="distance").nodes == [A, 6, B]
    assert 6 not in base and 11 in base.edges
    assert route(base, A, B, cost="distance").nodes == [A, B]


def test_an_edge_needs_both_nodes():
    with pytest.raises(RoutingError, match="no coordinates"):
        Graph({A: (0, 0)}, [Edge(1, A, B, 10)])


def test_a_cost_factor_makes_an_edge_dearer_for_both_costs():
    # T sits 943 m from both A and B, so each 1,400 m trail edge is longer than its chord.
    road = Graph(
        {A: (0, 0), B: (1000, 0), T: (500, 800)},
        [Edge(1, A, B, 1000, factor=1.5), Edge(2, A, T, 1400), Edge(3, T, B, 1400)],
    )
    # 1,000 m of road at 1.5x costs 1,500; 2,800 m of trail costs 2,800: the road still wins.
    assert route(road, A, B, cost="distance").nodes == [A, B]
    road.remove_edge(1)
    road.add_edge(Edge(4, A, B, 1000, factor=3.0))  # 3,000 > 2,800: now the trail wins
    assert route(road, A, B, cost="distance").nodes == [A, T, B]
    assert route(road, A, B, cost="naismith").nodes == [A, T, B]


def test_a_cost_factor_below_one_is_refused():
    with pytest.raises(RoutingError, match="must be >= 1"):
        Edge(1, A, B, 10, factor=0.5)
