"""
USGS NHD adapters: streams, rivers, lakes, ponds and wetlands.

Two adapters, both writing to WaterFeature: `nhd-flowlines` (lines) and
`nhd-waterbodies` (polygons). They share everything except which layer they read and how
they classify it.

Service
-------
https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer -- a MapServer, not a
FeatureServer. There is no NHD FeatureServer; the layers support /query all the same.

NHD was retired on 1 October 2023. It is still served and queryable but frozen and no
longer maintained, so the data will not improve. We target it anyway rather than its
successor, the 3D Hydrography Program: 3DHP classifies flowlines topologically (Canal,
Channel Line, Connector) and has **no perennial/intermittent equivalent**. That
distinction feeds the campsite score directly -- an intermittent stream is dry when you
need it -- so switching to 3DHP would silently cost a scoring input. Revisit when 3DHP
grows a flow-regime attribute.

Field case
----------
The flowline layer returns lowercase field names (`fcode`, `gnis_name`) and the waterbody
layer returns UPPERCASE (`FCODE`, `GNIS_NAME`) -- same service, same release, verified
live. Every lookup goes through `case_insensitive()` so a mis-cased key cannot silently
produce a null name or a null fcode.
"""

import json
from collections.abc import Iterable, Iterator

from django.contrib.gis.geos import GEOSGeometry

from geodata.models import WaterFeature
from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.registry import register
from pipeline.aoi import AreaOfInterest
from pipeline.arcgis import ArcGisError, ArcGisFeatureClient, case_insensitive

NHD_SERVICE = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"


class NhdError(ArcGisError):
    """Base for NHD-specific classification failures."""


class UnknownFeatureCode(NhdError):
    """NHD returned an FType or FCode we have no mapping for."""


# --- flowlines (layer 6, FType 460 = Stream/River) -------------------------------------

# Restricting to FType 460 server-side drops artificial paths, pipelines, canals,
# underground conduits and connectors -- 41% of features over the Adirondacks, and none of
# them are water a camper can drink from or camp beside.
#
# 46007 (Ephemeral) is included even though it does not occur in the Adirondacks: it is a
# real natural stream elsewhere, and excluding it would silently lose water features in
# drier regions when West Coast areas are configured.
FLOWLINE_FCODES = (46000, 46003, 46006, 46007)

# Labels confirmed from the live service's own renderer.
#
# 46000 maps to None rather than True. The service renderer draws it as "Perennial", but
# that is a cartographic grouping: in the NHD FCode scheme 46000 is Stream/River with no
# hydrographic qualifier, i.e. nobody recorded whether it runs year round. "We don't know"
# and "it runs year round" are different facts, and only one of them should raise a
# campsite's water score.
FLOWLINE_PERENNIAL = {
    46000: None,  # Stream/River, unqualified
    46003: False,  # Intermittent
    46006: True,  # Perennial
    46007: False,  # Ephemeral -- flows only after rain
}


# --- waterbodies (layer 12) ------------------------------------------------------------

# Keyed on FType, the coarse class, rather than on FCode. The waterbody layer carries 17
# distinct FCodes over the Adirondacks alone, most of which are construction details of
# reservoirs (treatment, tailings, cooling, filtration). FType collapses those to the six
# classes the service's own renderer names, which is the level our model cares about.
WATERBODY_FEATURE_TYPES = {
    390: WaterFeature.FeatureType.LAKE,  # Lake Pond
    436: WaterFeature.FeatureType.LAKE,  # Reservoir -- still a body of standing water
    466: WaterFeature.FeatureType.WETLAND,  # Swamp Marsh
    493: WaterFeature.FeatureType.OTHER,  # Estuary -- tidal, not drinkable
    378: WaterFeature.FeatureType.OTHER,  # Ice Mass
    361: WaterFeature.FeatureType.OTHER,  # Playa -- dry most of the year
}

# Only the FCodes that actually state a flow regime. Anything else resolves to None,
# which is the honest answer rather than a guess -- reservoir FCodes, for instance,
# describe construction rather than whether the water persists.
WATERBODY_PERENNIAL = {
    39000: None,  # Lake/Pond, unqualified
    39001: False,  # Lake/Pond: Intermittent
    39004: True,  # Lake/Pond: Perennial
    39009: True,  # Lake/Pond: Perennial, average water elevation
    39010: True,  # Lake/Pond: Perennial, normal pool
    39011: True,  # Lake/Pond: Perennial, date of photography
    39012: True,  # Lake/Pond: Perennial, spillway elevation
    46600: None,  # Swamp/Marsh, unqualified
    46601: False,  # Swamp/Marsh: Intermittent
    46602: True,  # Swamp/Marsh: Perennial
}


class NhdAdapter(SourceAdapter):
    """Shared behaviour for the two NHD layers. Not registered; see the subclasses."""

    source = WaterFeature.Source.NHD
    model = WaterFeature

    # We request outSR=4326, so the framework's reprojection is a deliberate no-op. Note
    # the model docstring's "NHD is native 4269" refers to the file download, not this
    # REST service, which is natively 3857 and honours outSR.
    source_srid = AreaOfInterest.SRID

    # Measured, not copied from the OSM adapter -- the volume profile is different.
    # ArcGIS resultOffset degrades linearly with depth on this service: a 2,000-feature
    # page costs 3.7s at offset 0, 9.3s at 10,000, 15.9s at 30,000 and 25.5s at 44,000.
    # At 0.5 degrees the densest Adirondack tile holds 2,723 flowlines, so no request ever
    # pages past offset 2,000 where every page is still around 4 seconds. A 1.0 degree
    # tile would hold 9,723 and reach offset 8,000, buying nothing for the extra latency.
    max_tile_degrees = 0.5

    page_size = 1000
    max_pages = 500
    timeout_seconds = 120

    layer_id: int = 0
    where_clause: str = "1=1"

    def __init__(self, client: ArcGisFeatureClient | None = None):
        super().__init__()
        self.client = client or ArcGisFeatureClient(
            f"{NHD_SERVICE}/{self.layer_id}/query",
            page_size=self.page_size,
            max_pages=self.max_pages,
            timeout_seconds=self.timeout_seconds,
        )

    def fetch(self, aoi: AreaOfInterest) -> Iterator[list[dict]]:
        """Page this layer over one tile. Tiling splits the area; paging walks a tile."""
        yield from self.client.iter_pages(aoi, where=self.where_clause)

    def normalize(self, raw: Iterable[list[dict]]) -> Iterator[dict]:
        for page in raw:
            for feature in page:
                yield self.to_record(feature)

    def to_record(self, feature: dict) -> dict:
        # Case-folded once here so neither layer's casing can leak into the mappings.
        properties = case_insensitive(feature.get("properties") or {})
        geometry = feature.get("geometry")

        if not geometry:
            raise NhdError(
                "NHD feature has no geometry (permanent_identifier "
                f"{properties.get('permanent_identifier')!r})"
            )

        # GeoJSON from this service carries "crs": null even with outSR=4326, so the SRID
        # comes from what we requested, never from the payload.
        geom = GEOSGeometry(json.dumps(geometry), srid=AreaOfInterest.SRID)

        return {
            "source_id": self.source_id_for(properties),
            "name": (properties.get("gnis_name") or "").strip()[:255],
            "geom": geom,
            "feature_type": self.feature_type_for(properties),
            "perennial": self.perennial_for(properties),
            "raw": properties,
        }

    @staticmethod
    def source_id_for(properties: dict) -> str:
        """permanent_identifier is NHD's own stable key -- nothing to synthesize."""
        identifier = properties.get("permanent_identifier")
        if not identifier:
            raise NhdError(
                "NHD feature has no permanent_identifier, so it cannot be upserted "
                f"idempotently. Properties present: {sorted(properties)}"
            )
        return str(identifier)

    @staticmethod
    def fcode_of(properties: dict) -> int:
        code = properties.get("fcode")
        if code is None:
            raise UnknownFeatureCode(
                f"NHD feature has no fcode; properties present: {sorted(properties)}"
            )
        return int(code)

    def feature_type_for(self, properties: dict) -> str:
        raise NotImplementedError

    def perennial_for(self, properties: dict) -> bool | None:
        raise NotImplementedError

    def run_parameters(self, aoi: AreaOfInterest) -> dict:
        parameters = super().run_parameters(aoi)
        parameters.update(
            service_url=self.client.service_url,
            layer_id=self.layer_id,
            where=self.where_clause,
            max_tile_degrees=self.max_tile_degrees,
        )
        return parameters


@register
class NhdFlowlinesAdapter(NhdAdapter):
    """Streams and rivers from NHD layer 6."""

    name = "nhd-flowlines"
    layer_id = 6
    where_clause = f"fcode IN ({','.join(str(code) for code in FLOWLINE_FCODES)})"

    def feature_type_for(self, properties: dict) -> str:
        # The where clause admits only FType 460, so everything here is a stream or river.
        return WaterFeature.FeatureType.STREAM

    def perennial_for(self, properties: dict) -> bool | None:
        code = self.fcode_of(properties)
        try:
            return FLOWLINE_PERENNIAL[code]
        except KeyError:
            raise UnknownFeatureCode(
                f"NHD flowline returned fcode {code}, which the server filter should have "
                f"excluded. Known flowline codes: "
                f"{', '.join(str(c) for c in sorted(FLOWLINE_PERENNIAL))}. "
                "Map it deliberately rather than guessing whether it holds water."
            ) from None


@register
class NhdWaterbodiesAdapter(NhdAdapter):
    """Lakes, ponds, reservoirs and wetlands from NHD layer 12."""

    name = "nhd-waterbodies"
    layer_id = 12

    def feature_type_for(self, properties: dict) -> str:
        ftype = properties.get("ftype")
        if ftype is None:
            raise UnknownFeatureCode(
                f"NHD waterbody has no ftype; properties present: {sorted(properties)}"
            )
        try:
            return WATERBODY_FEATURE_TYPES[int(ftype)]
        except KeyError:
            raise UnknownFeatureCode(
                f"NHD waterbody returned ftype {ftype}, which has no mapping. Known "
                f"types: {', '.join(str(t) for t in sorted(WATERBODY_FEATURE_TYPES))}. "
                "Map it deliberately rather than defaulting to OTHER, which would hide a "
                "whole class of water from the score."
            ) from None

    def perennial_for(self, properties: dict) -> bool | None:
        # Unmapped codes resolve to None. That is not a silent default: most waterbody
        # FCodes describe construction rather than flow regime, so "unknown" is the
        # accurate answer for them.
        return WATERBODY_PERENNIAL.get(self.fcode_of(properties))
