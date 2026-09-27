"""
OSM trails adapter: the hiking trail network, from OpenStreetMap via Overpass.

Why OSM and not a government source: trail geometry is community-maintained and far more
complete than any federal dataset for the Northeast. It is also the only realistic source
of Adirondack trail coverage, since the park is New York state land.

Ordered node IDs are the point
------------------------------
Trail.osm_node_ids stores the way's node references **in order**, never as a set. Two
ways that meet at a junction share a node ID, and that shared ID is what turns a pile of
disconnected line segments into a routable graph in a later sprint. Order matters as much
as membership: reversing a way reverses the direction of travel along it.

`out geom` is used rather than `out body` because it returns the node ID array *and* the
inline coordinates in a single response -- verified on a 2,423-way tile where every way
had `len(nodes) == len(geometry)`. `out body` would give node IDs without coordinates,
forcing a recursion step and a second lookup for the same data.

Relations are not ingested
--------------------------
`route=hiking` relations -- 271 of them over the Adirondack bounding box -- group existing
ways into named long-distance routes. They carry no geometry of their own, only member
references, so ingesting them would mean resolving members and stitching them together.

Skipping them costs the *route grouping*, not the geometry: every member way is already
captured by the highway query below, so no trail is missing from the map. What is missing
is the ability to say "this segment belongs to the Northville-Placid Trail" when the
segment itself is untagged. Roughly 40% of ways in a sampled tile carry no name of their
own, so that is a real gap for naming and for multi-day route planning. It is recoverable
later without re-ingesting, because relation membership can be fetched separately and
joined on the way IDs we already store.
"""

from collections.abc import Iterable, Iterator

from django.contrib.gis.geos import LineString

from geodata.models import Trail
from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.registry import register
from pipeline.aoi import AreaOfInterest
from pipeline.geometry import geodesic_length_m
from pipeline.overpass import OverpassClient

# The tags that constitute a walkable trail for our purposes. footway is included even
# though it also covers urban pavement, because in the Northeast it is widely used for
# trail segments near trailheads and huts -- excluding it wholesale would lose real trail.
TRAIL_HIGHWAY_VALUES = ("path", "footway", "track", "bridleway")

# What `highway=footway` means is decided by its `footway` subtag, and these four values
# say "urban pedestrian infrastructure" unambiguously. A crossing is a painted line over a
# road; a sidewalk runs beside one. Neither is somewhere you can camp, and on the previous
# ingest they were 7,471 of 26,005 rows -- Saranac Lake and Lake Placid street furniture
# sitting in a backcountry trail network.
EXCLUDED_FOOTWAY_VALUES = ("sidewalk", "crossing", "traffic_island", "access_aisle")

# Golf cart paths. Tagged highway=path or footway with a `golf` key; 548 rows previously.
EXCLUDED_IF_TAGGED = ("golf",)

# Deliberately NOT excluded, though it looks tempting:
#
#   tiger:*        2,578 rows carry tags from the US Census road import. Excluding them
#                  wholesale would drop 2,573 ways that are not urban at all -- 2,154 of
#                  them highway=track, 958 named, 51 carrying sac_scale. Those are
#                  Adirondack forest roads and logging tracks that happen to have come in
#                  through TIGER. They are exactly the kind of approach route this project
#                  cares about.
#
#   no sac_scale   Only 758 of 26,005 ways carry a hiking difficulty grade, so requiring
#                  one would discard 97% of the network including most real trail. Absence
#                  of the tag means nobody graded it, not that it is a pavement.
#
#   informal=yes   650 rows. Herd paths are unofficial but genuinely walked, and in the
#                  High Peaks they are often the only route up a trailless summit.


def is_hiking_trail(tags: dict) -> bool:
    """Whether a way with these tags belongs in the trail network.

    The Overpass query already excludes these server-side -- this is the same rule
    expressed once more, applied to whatever actually comes back. Keeping it as a
    predicate means the decision is testable without the network, and means a change in
    Overpass semantics shows up as a filtered record rather than a sidewalk on the map.
    """
    if (tags.get("footway") or "").strip() in EXCLUDED_FOOTWAY_VALUES:
        return False
    return all(key not in tags for key in EXCLUDED_IF_TAGGED)


@register
class OsmTrailsAdapter(SourceAdapter):
    """Hiking trails from OpenStreetMap."""

    name = "osm-trails"
    source = Trail.Source.OSM
    model = Trail

    # Overpass returns WGS84 lat/lon directly, so the framework's reprojection is a no-op.
    source_srid = AreaOfInterest.SRID

    # Measured, not guessed. A 1.0 degree tile over the densest part of the Adirondacks
    # (the High Peaks) returned 6,118 ways / 10 MB in 4 seconds -- far inside the 180
    # second server timeout. That gives 6 tiles for the Adirondacks and 25 for Maine.
    # 0.5 degrees was also tested (2,423 ways / 4.5 MB / 2 s) but would mean 20 and 81
    # tiles respectively, which is a lot of traffic for a service with 2 shared slots and
    # bought no measured headroom.
    max_tile_degrees = 1.0

    # Server-side limit for the query itself, distinct from the HTTP timeout.
    query_timeout_seconds = 180

    def __init__(self, client: OverpassClient | None = None):
        super().__init__()
        # Injectable so tests never touch the network, and so an OSM campsites adapter
        # can share a configured client later.
        self.client = client or OverpassClient(timeout_seconds=self.query_timeout_seconds)

    # --- fetch ------------------------------------------------------------------------

    def build_query(self, aoi: AreaOfInterest) -> str:
        """Overpass QL for every trail way intersecting `aoi`.

        The exclusions run server-side so the urban paths are never transferred at all.
        In Overpass a negated match also succeeds when the key is absent, so
        ["footway"!~"..."] keeps every way that has no footway subtag.
        """
        pattern = "|".join(TRAIL_HIGHWAY_VALUES)
        excluded_footway = "|".join(EXCLUDED_FOOTWAY_VALUES)
        drop_if_tagged = "".join(f'["{key}"!~"."]' for key in EXCLUDED_IF_TAGGED)
        return (
            f"[out:json][timeout:{self.query_timeout_seconds}];"
            f'way["highway"~"^({pattern})$"]'
            f'["footway"!~"^({excluded_footway})$"]'
            f"{drop_if_tagged}"
            f"({aoi.as_overpass_bbox()});"
            f"out geom;"
        )

    def fetch(self, aoi: AreaOfInterest) -> Iterator[list[dict]]:
        """One Overpass call per area, yielding its elements as a single page.

        The framework calls this once per tile, so a whole region is never held at once.
        """
        payload = self.client.query(self.build_query(aoi))
        yield payload["elements"]

    # --- normalize --------------------------------------------------------------------

    def normalize(self, raw: Iterable[list[dict]]) -> Iterator[dict]:
        for elements in raw:
            for element in elements:
                if element.get("type") != "way":
                    continue
                if not is_hiking_trail(element.get("tags") or {}):
                    continue
                yield self.to_record(element)

    def to_record(self, way: dict) -> dict:
        """One Overpass way to one Trail field dict."""
        tags = way.get("tags") or {}
        node_ids = list(way.get("nodes") or [])
        geometry = way.get("geometry") or []

        coordinates = [(point["lon"], point["lat"]) for point in geometry]

        # A way needs two distinct points to be a line. Emitting the record without
        # geometry lets the framework skip it and say why in IngestRun.notes, rather
        # than dropping it silently here.
        geom = LineString(coordinates, srid=AreaOfInterest.SRID) if len(coordinates) >= 2 else None

        # LineString is left as-is: the framework promotes it into the MultiLineString
        # column. Coercing here would duplicate a shared concern.

        return {
            "source_id": self.source_id_for(way),
            "name": (tags.get("name") or "").strip()[:255],
            "geom": geom,
            "trail_type": (tags.get("highway") or "").strip()[:32],
            "length_m": geodesic_length_m(coordinates) if coordinates else None,
            "osm_node_ids": node_ids,
            "raw": {"id": way.get("id"), "type": "way", "tags": tags},
        }

    @staticmethod
    def source_id_for(way: dict) -> str:
        """OSM way IDs are genuinely stable, so no synthesis is needed here.

        Prefixed with the element type because OSM numbers nodes, ways and relations in
        separate sequences -- node 12345 and way 12345 are both real and unrelated. A
        future campsites adapter writes node/12345 into a different table, but keeping
        the prefix means IDs stay unambiguous if the two are ever compared.
        """
        return f"way/{way['id']}"

    def run_parameters(self, aoi: AreaOfInterest) -> dict:
        parameters = super().run_parameters(aoi)
        parameters.update(
            endpoint=self.client.endpoint,
            highway_values=list(TRAIL_HIGHWAY_VALUES),
            excluded_footway_values=list(EXCLUDED_FOOTWAY_VALUES),
            excluded_if_tagged=list(EXCLUDED_IF_TAGGED),
            max_tile_degrees=self.max_tile_degrees,
        )
        return parameters
