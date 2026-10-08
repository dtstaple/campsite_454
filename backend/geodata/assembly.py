"""
A trail for a clicked way (TM05-97): its named route if it has one, otherwise a trail
assembled from the connected ways that share its name.

Most named Adirondack trail ways (3,652 of 4,494) belong to no `route=hiking` relation, so
they have no TrailRoute and the trail panel had nothing to open. The Adirondack Rail Trail
is the case that surfaced it: `highway=path`, and in OSM its only relation is
`route=railway` (the old Adirondack Branch line), which the route ingest rightly ignores.

Assembly walks the way graph the ingest already preserved: two ways connect when they
share an OSM node id (`Trail.osm_node_ids`). Starting from the clicked way, it collects
every way with the same name (case-insensitive) reachable through shared nodes.

Shared nodes alone are not enough. The Rail Trail's 55 ways fall into 19 groups that
share no node: mappers stopped each way a few metres short at road crossings and
bridges, leaving gaps of 4.7-12.7 m. So two same-name ways whose ends are within
ENDPOINT_JOIN_M (15 m) also connect. That is well under the 50 m the profile's stitching
already tolerates, and the name must match, so unrelated trails are not joined. The
members are ordered by OSM id, so whichever segment a user clicks, the assembled geometry,
and therefore its cached elevation profile, is the same.

Short unnamed connectors (TM05-98). Mappers also split a named trail with a short way that
carries no name: a bridge, a boardwalk, a road crossing. Two same-name pieces are joined
through unnamed ways that share OSM nodes with both, when the connectors' combined length
is at most `assembly.connector_max_m` in routes.yml (300 m). The search only ever steps
onto unnamed ways, so a gap is never bridged through another named trail. It takes the
shortest connector path, so it is the same from either side.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict, deque

from django.contrib.gis.geos import MultiLineString
from django.contrib.gis.measure import D

from geodata.models import METRIC_SRID, Trail, TrailRoute
from geodata.route_rating import config as route_config

#: Only ways within this distance of the clicked one are considered. Generous: the longest
#: Adirondack routes run well over 100 km.
SEARCH_RADIUS_KM = 150
#: Safety caps against a very common name ("Trail") pulling in half the region.
MAX_CANDIDATES = 5000
MAX_MEMBERS = 1000
#: Same-name ways whose ends are this close connect even without a shared node.
ENDPOINT_JOIN_M = 15.0
#: Bounds on the connector search, per bridge, against a dense web of unnamed paths.
MAX_CONNECTOR_STEPS = 500

TRAIL_FIELDS = ("id", "source_id", "name", "geom", "geom_m", "length_m", "osm_node_ids")


def connector_max_m() -> float:
    return float(route_config().get("assembly", {}).get("connector_max_m", 0) or 0)


def way_number(source_id: str) -> int | None:
    kind, _, number = source_id.partition("/")
    return int(number) if kind == "way" and number.isdigit() else None


def route_for_way(way: Trail) -> TrailRoute | None:
    """The longest named route that has this way as a member, if any."""
    number = way_number(way.source_id)
    if number is None:
        return None
    return (
        TrailRoute.objects.filter(member_way_ids__contains=[number])
        .exclude(name="")
        .order_by("-length_m", "osm_id")
        .first()
    )


def connected_same_name(way: Trail, max_connector_m: float | None = None) -> list[Trail]:
    """Every way with `way`'s name reachable from it through shared OSM nodes (or ends
    within ENDPOINT_JOIN_M), plus the short unnamed connectors that bridge same-name
    pieces (TM05-98), by id."""
    if max_connector_m is None:
        max_connector_m = connector_max_m()
    name = (way.name or "").strip()
    nearby = (way.geom_m, D(km=SEARCH_RADIUS_KM))
    candidates = list(
        Trail.objects.filter(name__iexact=name, geom_m__dwithin=nearby).only(*TRAIL_FIELDS)[
            :MAX_CANDIDATES
        ]
    )
    by_node: dict[int, list[Trail]] = defaultdict(list)
    for candidate in candidates:
        for node in candidate.osm_node_ids or []:
            by_node[node].append(candidate)

    # Ends, bucketed on a grid of ENDPOINT_JOIN_M cells, so the near-end check only looks
    # at the 3 x 3 cells around an end rather than at every candidate.
    by_cell: dict[tuple[int, int], list[tuple[Trail, tuple[float, float]]]] = defaultdict(list)
    for candidate in candidates:
        for end in ends_of(candidate):
            by_cell[cell(end)].append((candidate, end))

    def neighbours(current: Trail):
        for node in current.osm_node_ids or []:
            yield from by_node.get(node, ())
        for end in ends_of(current):
            cx, cy = cell(end)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for other, other_end in by_cell.get((cx + dx, cy + dy), ()):
                        if math.dist(end, other_end) <= ENDPOINT_JOIN_M:
                            yield other

    seen: set[int] = set()
    members: list[Trail] = []

    def absorb(start: Trail) -> None:
        seen.add(start.pk)
        members.append(start)
        queue = deque([start])
        while queue and len(members) < MAX_MEMBERS:
            current = queue.popleft()
            for neighbour in neighbours(current):
                if neighbour.pk not in seen:
                    seen.add(neighbour.pk)
                    members.append(neighbour)
                    queue.append(neighbour)

    absorb(way)
    if max_connector_m > 0:
        while len(members) < MAX_MEMBERS:
            bridge = find_bridge(members, by_node, seen, max_connector_m)
            if bridge is None:
                break
            connectors, target = bridge
            for connector in connectors:
                if connector.pk not in seen:
                    seen.add(connector.pk)
                    members.append(connector)
            absorb(target)
    return sorted(members, key=lambda member: way_number(member.source_id) or 0)


def _unnamed_touching(geom, max_length_m: float) -> list[Trail]:
    """Unnamed ways no longer than `max_length_m` that touch `geom` (METRIC_SRID)."""
    return list(
        Trail.objects.filter(name="", length_m__lte=max_length_m)
        .filter(geom_m__dwithin=(geom, D(m=1)))
        .only(*TRAIL_FIELDS)
    )


def find_bridge(
    members: list[Trail],
    same_name_by_node: dict[int, list[Trail]],
    seen: set[int],
    max_connector_m: float,
) -> tuple[list[Trail], Trail] | None:
    """The shortest path of unnamed connectors, at most `max_connector_m` long in total,
    from the assembled trail to a same-name way not yet in it: (connectors, that way).

    Only unnamed ways are ever stepped onto, so no gap is bridged through a named trail.
    Each step must share an OSM node with the one before it."""
    member_nodes = {node for member in members for node in member.osm_node_ids or []}
    union = MultiLineString(
        [line for member in members for line in (member.geom_m or [])], srid=METRIC_SRID
    )
    starts = [
        connector
        for connector in _unnamed_touching(union, max_connector_m)
        if connector.pk not in seen and member_nodes.intersection(connector.osm_node_ids or [])
    ]
    # Dijkstra over connectors by total length; ties broken by way id, so it is stable.
    heap = [
        ((c.length_m or 0), way_number(c.source_id) or 0, index, [c])
        for index, c in enumerate(starts)
    ]
    heapq.heapify(heap)
    counter = len(heap)
    visited: set[int] = set()
    steps = 0
    while heap and steps < MAX_CONNECTOR_STEPS:
        length, _, _, path = heapq.heappop(heap)
        connector = path[-1]
        if connector.pk in visited:
            continue
        visited.add(connector.pk)
        steps += 1
        for node in connector.osm_node_ids or []:
            for target in same_name_by_node.get(node, ()):
                if target.pk not in seen:
                    return path, target
        for following in _unnamed_touching(connector.geom_m, max_connector_m - length):
            total = length + (following.length_m or 0)
            if (
                following.pk in visited
                or following.pk in seen
                or total > max_connector_m
                or not set(connector.osm_node_ids or []).intersection(following.osm_node_ids or [])
            ):
                continue
            counter += 1
            heapq.heappush(
                heap, (total, way_number(following.source_id) or 0, counter, [*path, following])
            )
    return None


def ends_of(trail: Trail) -> list[tuple[float, float]]:
    """The metric start and end of every line in a way's geometry."""
    geom = trail.geom_m
    if geom is None:
        geom = trail.geom.transform(METRIC_SRID, clone=True)
    return [coords for line in geom for coords in (line.coords[0], line.coords[-1])]


def cell(point: tuple[float, float]) -> tuple[int, int]:
    return (math.floor(point[0] / ENDPOINT_JOIN_M), math.floor(point[1] / ENDPOINT_JOIN_M))


def assembled_route(way: Trail) -> TrailRoute:
    """An unsaved TrailRoute standing for the assembled trail, with `geom_m` set, so the
    route detail code (profile, campsites along, rating) treats it like any route."""
    members = connected_same_name(way)
    lines = [line for member in members for line in member.geom]
    geom = MultiLineString(lines, srid=4326)
    numbers = [way_number(member.source_id) for member in members]
    route = TrailRoute(
        source=TrailRoute.Source.OSM,
        source_id=f"assembled/{members[0].source_id}",
        osm_id=None,
        name=(way.name or "").strip(),
        geom=geom,
        length_m=sum(member.length_m or 0 for member in members),
        member_way_ids=[number for number in numbers if number is not None],
    )
    route.geom_m = geom.transform(METRIC_SRID, clone=True)
    return route
