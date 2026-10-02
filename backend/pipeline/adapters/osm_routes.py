"""
OSM routes adapter: named hiking routes from `route=hiking` relations (TM05-58).

The trails adapter ingests OSM *ways*: segments between junctions, ~40% of them unnamed.
A relation groups ways into the route a hiker actually names -- the Van Hoevenberg Trail,
the Northville-Placid Trail. This adapter stores those relations as TrailRoute rows.

Measured live, 2026-10-02: 271 relations over the Adirondack box (5.0 MB, 8 s) and 182
over the White Mountains (3.0 MB, 38 s including two Overpass 504 retries). `out geom`
returns every member way's coordinates inline -- 3,491 of 3,491 and 1,237 of 1,237 -- so
no second lookup is needed.

Decisions
---------
- One query per region, not per 1-degree tile. A long route crosses tiles, so tiling would
  transfer the same relation (with its full geometry) once per tile. The responses above
  are well inside Overpass limits for a single query.
- Member order is the relation's order. `member_way_ids` keeps every way, every role.
- `geom` and `length_m` use main-line members only. Roles alternative / excursion /
  approach / connection are side branches; counting them would make a route longer than
  anyone walks it. A way listed twice (once forward, once backward) counts once.
- Nested relations are not expanded. A super-relation (the Appalachian Trail is one, made of
  per-state sections) has relation members rather than ways. Its child sections are
  themselves route=hiking relations, so they are ingested in their own right when they
  intersect the region. A relation with no way members has no geometry and is skipped,
  with the reason recorded in the run notes by the framework.
- The whole route is stored, including parts outside the region box, because a route's
  length and profile mean nothing half-clipped.
"""

from collections.abc import Iterable, Iterator

from django.contrib.gis.geos import LineString, MultiLineString

from geodata.models import TrailRoute
from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.registry import register
from pipeline.aoi import AreaOfInterest
from pipeline.geometry import geodesic_length_m
from pipeline.overpass import OverpassClient

#: Member roles that are side branches rather than the route itself.
SIDE_BRANCH_ROLES = frozenset({"alternative", "excursion", "approach", "connection"})


@register
class OsmRoutesAdapter(SourceAdapter):
    """Named hiking routes from OpenStreetMap route relations."""

    name = "osm-routes"
    source = TrailRoute.Source.OSM
    model = TrailRoute
    source_srid = AreaOfInterest.SRID

    # No tiling: each region is one query. See the module docstring for why tiling is
    # wrong for relations.
    max_tile_degrees = None
    query_timeout_seconds = 180

    def __init__(self, client: OverpassClient | None = None):
        super().__init__()
        self.client = client or OverpassClient(timeout_seconds=self.query_timeout_seconds)

    def build_query(self, aoi: AreaOfInterest) -> str:
        return (
            f"[out:json][timeout:{self.query_timeout_seconds}];"
            f'relation["route"="hiking"]({aoi.as_overpass_bbox()});'
            f"out geom;"
        )

    def fetch(self, aoi: AreaOfInterest) -> Iterator[list[dict]]:
        payload = self.client.query(self.build_query(aoi))
        yield payload["elements"]

    def normalize(self, raw: Iterable[list[dict]]) -> Iterator[dict]:
        for elements in raw:
            for element in elements:
                if element.get("type") == "relation":
                    yield self.to_record(element)

    def to_record(self, relation: dict) -> dict:
        tags = relation.get("tags") or {}
        members = relation.get("members") or []
        way_members = [m for m in members if m.get("type") == "way"]

        lines, length, seen = [], 0.0, set()
        for member in way_members:
            if (member.get("role") or "") in SIDE_BRANCH_ROLES or member["ref"] in seen:
                continue
            seen.add(member["ref"])
            coordinates = [(p["lon"], p["lat"]) for p in member.get("geometry") or [] if p]
            if len(coordinates) >= 2:
                lines.append(LineString(coordinates, srid=AreaOfInterest.SRID))
                length += geodesic_length_m(coordinates)

        return {
            "source_id": f"relation/{relation['id']}",
            "osm_id": relation["id"],
            "name": (tags.get("name") or tags.get("ref") or "").strip()[:255],
            "ref": (tags.get("ref") or "").strip()[:64],
            "network": (tags.get("network") or "").strip()[:32],
            "operator": (tags.get("operator") or "").strip()[:128],
            "member_way_ids": [m["ref"] for m in way_members],
            # None when there are no usable way members (a pure super-relation): the
            # framework skips the record and records why.
            "geom": MultiLineString(lines, srid=AreaOfInterest.SRID) if lines else None,
            "length_m": length or None,
            "raw": {
                "id": relation["id"],
                "type": "relation",
                "tags": tags,
                "members": [
                    {"type": m.get("type"), "ref": m.get("ref"), "role": m.get("role", "")}
                    for m in members
                ],
            },
        }

    def run_parameters(self, aoi: AreaOfInterest) -> dict:
        parameters = super().run_parameters(aoi)
        parameters.update(
            endpoint=self.client.endpoint,
            side_branch_roles=sorted(SIDE_BRANCH_ROLES),
            max_tile_degrees=self.max_tile_degrees,
        )
        return parameters
