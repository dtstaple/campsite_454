"""
Connecting trails (TM05-101): the other named trails that meet this one at a junction.

A junction is an OSM node that one of this trail's ways and another named way both pass
through: the ways share an entry in `Trail.osm_node_ids`. A trail that merely crosses or
comes close, with no shared node, is not connected; OSM puts a node wherever two paths
really meet. Each way's node ids are in vertex order (the adapter keeps them so), so a
junction's position is the vertex at that node's index, exactly.

The other trail is identified the way the trail panel opens trails: its named route when
it is a member of one (TM05-58), otherwise the assembled trail of its name (TM05-97,
opened through that way). Ways with this trail's own name are left out, so are unnamed
ways. Junctions are placed along this trail's stitched line, so their miles match the
panel's. Combining trails into one hike is a later story; this only lists them.
"""

from __future__ import annotations

from collections import defaultdict

from django.contrib.gis.geos import LineString, Point
from django.contrib.gis.measure import D

from geodata.assembly import way_number
from geodata.models import METRIC_SRID, Trail, TrailRoute

#: Junctions with the same trail closer than this along the line are one junction (a
#: trail that touches twice at a switchback is still one place on the map).
MERGE_ALONG_M = 50.0
MAX_CONNECTIONS = 40


def member_ways(route: TrailRoute) -> list[Trail]:
    ids = [f"way/{number}" for number in route.member_way_ids or []]
    return list(
        Trail.objects.filter(source_id__in=ids).only("id", "source_id", "name", "osm_node_ids")
    )


def routes_by_way(route: TrailRoute) -> dict[int, TrailRoute]:
    """For every way of the named routes touching `route`: the route that way opens, as
    route_for_way chooses it (the longest, then the lowest relation id). One query for all
    of them, rather than one per connecting way."""
    nearby = (
        TrailRoute.objects.filter(geom_m__dwithin=(route.geom_m, D(m=5)))
        .exclude(name="")
        .only("id", "osm_id", "name", "length_m", "member_way_ids")
        .order_by("-length_m", "osm_id")
    )
    chosen: dict[int, TrailRoute] = {}
    for candidate in nearby:
        for number in candidate.member_way_ids or []:
            chosen.setdefault(number, candidate)
    return chosen


def _vertex(way: Trail, node: int):
    """(metric point, lon/lat point) of the way's vertex at `node`, or None."""
    nodes = way.osm_node_ids or []
    if node not in nodes or not way.geom or len(way.geom) != 1:
        return None
    index = nodes.index(node)
    line, line_m = way.geom[0], way.geom_m[0]
    if index >= len(line.coords) or len(line.coords) != len(nodes):
        return None
    return Point(line_m.coords[index], srid=METRIC_SRID), Point(line.coords[index], srid=4326)


def connections(route: TrailRoute, line_m: LineString) -> list[dict]:
    """The named trails sharing a junction node with `route`, in order of their first
    junction along `line_m` (this route's stitched line, METRIC_SRID)."""
    members = member_ways(route)
    member_ids = {member.pk for member in members}
    nodes = {node for member in members for node in member.osm_node_ids or []}
    if not nodes or route.geom_m is None:
        return []
    own_name = (route.name or "").strip().lower()

    touching = (
        Trail.objects.filter(geom_m__dwithin=(route.geom_m, D(m=1)))
        .exclude(pk__in=member_ids)
        .exclude(name="")
        .only("id", "source_id", "name", "geom", "geom_m", "osm_node_ids")
    )
    routes = routes_by_way(route)
    found: dict[tuple, dict] = {}
    junctions: dict[tuple, list[dict]] = defaultdict(list)
    for way in touching:
        name = (way.name or "").strip()
        shared = nodes.intersection(way.osm_node_ids or [])
        if not shared or name.lower() == own_name:
            continue
        target = routes.get(way_number(way.source_id))
        if target is not None and route.osm_id is not None and target.osm_id == route.osm_id:
            continue
        if target is not None and target.name.strip().lower() == own_name:
            continue
        key = ("route", target.osm_id) if target else ("trail", name.lower())
        if key not in found:
            found[key] = {
                "name": target.name if target else name,
                "osm_id": target.osm_id if target else None,
                "way_id": None if target else way.source_id,
            }
        for node in sorted(shared):
            vertex = _vertex(way, node)
            if vertex is None:
                continue
            point_m, point = vertex
            junctions[key].append(
                {
                    "node_id": node,
                    "lon": round(point.x, 6),
                    "lat": round(point.y, 6),
                    "distance_along_m": round(line_m.project(point_m), 1),
                    "via_way": way.source_id,
                }
            )

    out = []
    for key, entry in found.items():
        places = sorted(junctions[key], key=lambda j: (j["distance_along_m"], j["node_id"]))
        merged: list[dict] = []
        for place in places:
            if (
                merged
                and place["distance_along_m"] - merged[-1]["distance_along_m"] < MERGE_ALONG_M
            ):
                continue
            merged.append(place)
        if not merged:
            continue
        # Open an assembled trail through its lowest-numbered way, so the same trail is
        # always opened the same way.
        if entry["way_id"]:
            ways = {place["via_way"] for place in merged}
            entry["way_id"] = min(ways, key=lambda s: way_number(s) or 0)
        for place in merged:
            place.pop("via_way")
        out.append({**entry, "junctions": merged})
    out.sort(key=lambda e: (e["junctions"][0]["distance_along_m"], e["name"].lower()))
    return out[:MAX_CONNECTIONS]
