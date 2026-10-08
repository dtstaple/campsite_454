"""
OSM campsites adapter: backcountry campsites from OpenStreetMap via Overpass.

Why this source exists
----------------------
RIDB is federal-only. The Adirondacks are New York State Forest Preserve, so RIDB returns
essentially nothing there, and the result was that the database held 660 campsites in the
White Mountains and 92,000 trails and water features in the Adirondacks, two regions three
hundred kilometres apart. No viewport anywhere on the map showed a campsite and a stream at
the same time, which is the entire product. OSM is the only source with real coverage of
state land, so this is what makes one region complete.

It is the right source on the merits too, not just by elimination. Of 230 `tourism=camp_site`
features sampled over the High Peaks, 153 carry `backcountry=yes` -- these are the
walk-in, no-facilities sites this project is actually about, and no federal dataset lists
them.

Nodes and ways, not relations
-----------------------------
A campsite is mapped either as a node (a point, 206 of that sample) or as a way (an area
you pitch inside, 22). Both are wanted and both become a Point here, because a campsite is
one spot to stand: `out center` asks Overpass for a representative point for the ways, so
neither case needs area handling downstream.

Relations -- 2 in that sample -- are not ingested, following the same decision as
`osm_trails`. A `tourism=camp_site` relation is a multipolygon grouping several ways, and
the ways it groups are already returned by the query below, so ingesting the relation would
duplicate sites already captured rather than add new ones. The queried element types are
recorded in every run's parameters, so a run states what it looked for rather than leaving
the omission implicit.

Lean-tos (TM05-75)
-----------------
Adirondack lean-tos are mostly mapped as `amenity=shelter` + `shelter_type=lean_to`, not
`tourism=camp_site`, so a camp_site-only query missed most of them and the High Peaks looked
sparse. The query now also asks for those shelters. They are places to spend the night,
first come first served, which is exactly what "campsites along this trail" is for.

- **Same element, one row.** A lean-to that is also tagged `tourism=camp_site` matches both
  selectors. Overpass's union returns each element once, and normalize() drops any repeat
  of a source_id within a batch as well, so it is ingested once, with site_type lean_to.
- **Nearby but separate elements are not merged.** A lean-to node a few metres from a
  separately mapped campsite is a different OSM element, and may be a different thing (the
  shelter, and tent pads beside it). Both are kept; the ingest command can report such pairs
  (within 15 m) for a human to look at.
- Other shelters (`shelter_type=picnic_shelter`, `basic_hut`, ...) are not campsites and are
  not asked for.

Site type is mapped narrowly on purpose
---------------------------------------
Only tags that say something unambiguous are mapped. `backcountry=yes` means primitive;
`group_only=yes` means group; a lean-to shelter means lean_to. Everything else stays
`unknown` rather than being promoted to `designated`, because `tourism=camp_site` on its own
says somebody mapped a camping spot, not that it is an official developed campground.
Guessing here would put a fact in front of a user that the source never asserted -- the same
reason `reservable` and `capacity` stay null when OSM is silent.
"""

from collections.abc import Iterable, Iterator

from django.contrib.gis.geos import Point

from geodata.models import Campsite
from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.registry import register
from pipeline.aoi import AreaOfInterest
from pipeline.overpass import OverpassClient

# The element types worth asking for. Relations are excluded at the query, not filtered
# out afterwards, so they are never transferred -- see the module docstring.
CAMPSITE_ELEMENT_TYPES = ("node", "way")

# Overpass tag filters, each one a set of features this adapter ingests (TM05-75 added the
# lean-to shelters). Recorded in every run's parameters.
TAG_FILTERS = (
    '["tourism"="camp_site"]',
    '["amenity"="shelter"]["shelter_type"="lean_to"]',
)

# OSM tag to Campsite.SiteType. Checked in order, first match wins, so the more specific
# shelter and group cases are tested before the broad backcountry one.
SITE_TYPE_RULES: tuple[tuple[str, str, str], ...] = (
    ("shelter_type", "lean_to", Campsite.SiteType.LEAN_TO),
    ("group_only", "yes", Campsite.SiteType.GROUP),
    ("backcountry", "yes", Campsite.SiteType.PRIMITIVE),
)

# OSM `reservation` values that answer the reservable question. Anything else -- including
# the tag being absent, which is the common case -- leaves it null, which the API and the
# popup both already treat as "not recorded" rather than "no".
RESERVATION_TRUE = ("required", "yes", "recommended")
RESERVATION_FALSE = ("no", "not_possible")


@register
class OsmCampsitesAdapter(SourceAdapter):
    """Backcountry campsites from OpenStreetMap."""

    name = "osm-campsites"
    source = Campsite.Source.OSM
    model = Campsite

    # Overpass returns WGS84 lat/lon directly, so the framework's reprojection is a no-op.
    source_srid = AreaOfInterest.SRID

    # Campsites are far sparser than trails -- 230 features over a 0.5 x 0.6 degree box
    # against 6,118 trail ways over a 1.0 degree one -- so the tile can be larger without
    # approaching the response sizes that forced osm_trails down to 1.0.
    max_tile_degrees = 2.0

    query_timeout_seconds = 180

    def __init__(self, client: OverpassClient | None = None):
        super().__init__()
        # Injectable so tests never touch the network, matching osm_trails.
        self.client = client or OverpassClient(timeout_seconds=self.query_timeout_seconds)

    # --- fetch ------------------------------------------------------------------------

    def build_query(self, aoi: AreaOfInterest) -> str:
        """Overpass QL for every campsite node and way intersecting `aoi`.

        `out center` rather than `out geom`: a way here is an area to pitch inside, and
        what the model stores is a single Point, so the representative point Overpass
        computes is exactly what is wanted and avoids transferring polygon rings that
        would only be collapsed on arrival. For a node it is a no-op.
        """
        bbox = aoi.as_overpass_bbox()
        parts = "".join(
            f"{element}{tags}({bbox});"
            for tags in TAG_FILTERS
            for element in CAMPSITE_ELEMENT_TYPES
        )
        return f"[out:json][timeout:{self.query_timeout_seconds}];({parts});out center;"

    def fetch(self, aoi: AreaOfInterest) -> Iterator[list[dict]]:
        """One Overpass call per area, yielding its elements as a single page."""
        payload = self.client.query(self.build_query(aoi))
        yield payload["elements"]

    # --- normalize --------------------------------------------------------------------

    def normalize(self, raw: Iterable[list[dict]]) -> Iterator[dict]:
        seen: set[str] = set()
        for elements in raw:
            for element in elements:
                if element.get("type") not in CAMPSITE_ELEMENT_TYPES:
                    continue
                # One row per OSM element, even if it matched two tag filters (TM05-75).
                source_id = self.source_id_for(element)
                if source_id in seen:
                    continue
                seen.add(source_id)
                yield self.to_record(element)

    def to_record(self, element: dict) -> dict:
        """One Overpass element to one Campsite field dict."""
        tags = element.get("tags") or {}
        point = self.point_for(element)

        return {
            "source_id": self.source_id_for(element),
            "name": (tags.get("name") or "").strip()[:255],
            "geom": point,
            "site_type": self.map_site_type(tags),
            "reservable": self.map_reservable(tags),
            "capacity": self.map_capacity(tags),
            "raw": {"id": element.get("id"), "type": element.get("type"), "tags": tags},
        }

    @staticmethod
    def point_for(element: dict) -> Point | None:
        """The campsite's location.

        A node carries lat/lon directly; a way carries `center` because the query asks for
        `out center`. Returning None when neither is present lets the framework skip the
        record and say why in IngestRun.notes, rather than dropping it silently here.
        """
        source = element if element.get("type") == "node" else (element.get("center") or {})
        lat, lon = source.get("lat"), source.get("lon")
        if lat is None or lon is None:
            return None
        return Point(float(lon), float(lat), srid=AreaOfInterest.SRID)

    @staticmethod
    def map_site_type(tags: dict) -> str:
        """First matching rule wins; anything unrecognised stays unknown."""
        for key, value, site_type in SITE_TYPE_RULES:
            if (tags.get(key) or "").strip().lower() == value:
                return site_type
        return Campsite.SiteType.UNKNOWN

    @staticmethod
    def map_reservable(tags: dict) -> bool | None:
        value = (tags.get("reservation") or "").strip().lower()
        if value in RESERVATION_TRUE:
            return True
        if value in RESERVATION_FALSE:
            return False
        return None

    @staticmethod
    def map_capacity(tags: dict) -> int | None:
        """OSM `capacity` is free text, so a non-numeric value is left null, not coerced."""
        raw_value = (tags.get("capacity") or "").strip()
        if not raw_value.isdigit():
            return None
        capacity = int(raw_value)
        # PositiveSmallIntegerField tops out at 32767; a larger value is a tagging error
        # and would raise on save, taking the whole batch with it.
        return capacity if 0 < capacity <= 32767 else None

    @staticmethod
    def source_id_for(element: dict) -> str:
        """`node/12345` or `way/12345`.

        Prefixed with the element type because OSM numbers nodes, ways and relations in
        separate sequences, so node 12345 and way 12345 are both real and unrelated. The
        prefix also keeps these distinct from RIDB's `campsite/12345` in the same table,
        which matters because the save endpoint resolves a campsite by source_id alone.
        """
        return f"{element['type']}/{element['id']}"

    def run_parameters(self, aoi: AreaOfInterest) -> dict:
        parameters = super().run_parameters(aoi)
        parameters.update(
            endpoint=self.client.endpoint,
            element_types=list(CAMPSITE_ELEMENT_TYPES),
            tourism_value="camp_site",
            tag_filters=list(TAG_FILTERS),
        )
        return parameters
