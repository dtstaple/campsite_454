"""
OSM connectors adapter (TM05-137): the roads and footways between trails.

The trail network (osm_trails.py) is paths, footways, tracks and bridleways, minus
sidewalks and crossings. In OSM, trails often join only through a short stretch of road:
the Hoffman Notch Trail ends on Blue Ridge Road, and 70 m along it a service road meets
the next trail. Without the road the router sees two unconnected networks. This adapter
fetches those roads, so the routing graph can walk them at a higher cost, with the route
labelled "road walk" (routing/build.py decides which stretches and how long).

What counts as walkable
-----------------------
- Roads: secondary, tertiary, unclassified, residential, living_street, and service.
  primary, trunk and motorway are left out: nobody plans a hike along them. secondary
  stays in, because that is what county and state roads between trailheads are tagged
  (Blue Ridge Road is one).
- Footways the trail filter excluded: sidewalks and crossings.
- Never: anything tagged access=private|no or foot=no, parking aisles and drive-throughs.
- Driveways are fetched, but the graph build keeps one only where it meets a trail, as
  the trail's own access from the road (routing/build.py). At the Hoffman Notch gap, the
  link from Blue Ridge Road to the "Branch Road" path is a gravel service=driveway with
  no access tag.
"""

from collections.abc import Iterable, Iterator

from django.contrib.gis.geos import LineString

from geodata.models import Connector
from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.registry import register
from pipeline.aoi import AreaOfInterest
from pipeline.geometry import geodesic_length_m
from pipeline.overpass import OverpassClient

ROAD_HIGHWAY_VALUES = (
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "service",
)
CONNECTOR_FOOTWAY_VALUES = ("sidewalk", "crossing")
EXCLUDED_SERVICE_VALUES = ("parking_aisle", "drive-through")
NO_ACCESS = ("private", "no")


def is_walkable_connector(tags: dict) -> bool:
    """Whether a way with these tags may be walked between trails."""
    highway = (tags.get("highway") or "").strip()
    if highway == "footway":
        if (tags.get("footway") or "").strip() not in CONNECTOR_FOOTWAY_VALUES:
            return False
    elif highway not in ROAD_HIGHWAY_VALUES:
        return False
    if (tags.get("access") or "").strip() in NO_ACCESS or (tags.get("foot") or "") == "no":
        return False
    return not (highway == "service" and tags.get("service") in EXCLUDED_SERVICE_VALUES)


@register
class OsmConnectorsAdapter(SourceAdapter):
    """Roads and sidewalks that connect trails, from OpenStreetMap."""

    name = "osm-connectors"
    source = Connector.Source.OSM
    model = Connector
    source_srid = AreaOfInterest.SRID
    # Roads are denser than trails around towns; half a degree keeps a tile well inside
    # the server timeout (measured on the Adirondacks: docs/routing.md).
    max_tile_degrees = 0.5
    query_timeout_seconds = 180

    def __init__(self, client: OverpassClient | None = None):
        super().__init__()
        self.client = client or OverpassClient(timeout_seconds=self.query_timeout_seconds)

    def build_query(self, aoi: AreaOfInterest) -> str:
        roads = "|".join(ROAD_HIGHWAY_VALUES)
        footways = "|".join(CONNECTOR_FOOTWAY_VALUES)
        bbox = aoi.as_overpass_bbox()
        return (
            f"[out:json][timeout:{self.query_timeout_seconds}];"
            f"("
            f'way["highway"~"^({roads})$"]({bbox});'
            f'way["highway"="footway"]["footway"~"^({footways})$"]({bbox});'
            f");"
            f"out geom;"
        )

    def fetch(self, aoi: AreaOfInterest) -> Iterator[list[dict]]:
        yield self.client.query(self.build_query(aoi))["elements"]

    def normalize(self, raw: Iterable[list[dict]]) -> Iterator[dict]:
        for elements in raw:
            for element in elements:
                if element.get("type") != "way":
                    continue
                if not is_walkable_connector(element.get("tags") or {}):
                    continue
                yield self.to_record(element)

    def to_record(self, way: dict) -> dict:
        tags = way.get("tags") or {}
        coordinates = [(p["lon"], p["lat"]) for p in way.get("geometry") or []]
        geom = LineString(coordinates, srid=AreaOfInterest.SRID) if len(coordinates) >= 2 else None
        return {
            "source_id": f"way/{way['id']}",
            "name": (tags.get("name") or tags.get("ref") or "").strip()[:255],
            "geom": geom,
            "highway": (tags.get("highway") or "").strip()[:32],
            "length_m": geodesic_length_m(coordinates) if coordinates else None,
            "osm_node_ids": list(way.get("nodes") or []),
            "raw": {"id": way.get("id"), "type": "way", "tags": tags},
        }

    def run_parameters(self, aoi: AreaOfInterest) -> dict:
        parameters = super().run_parameters(aoi)
        parameters.update(
            endpoint=self.client.endpoint,
            road_highway_values=list(ROAD_HIGHWAY_VALUES),
            connector_footway_values=list(CONNECTOR_FOOTWAY_VALUES),
            excluded_service_values=list(EXCLUDED_SERVICE_VALUES),
            max_tile_degrees=self.max_tile_degrees,
        )
        return parameters
