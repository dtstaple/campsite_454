"""
PAD-US adapter: public land boundaries and legal camping access.

Source: the USGS Protected Areas Database, served as an ArcGIS REST feature layer. We
query it by bounding box rather than downloading the national geodatabase, because a
region needs only one to eight thousand polygons out of a multi-gigabyte file.

Projection note: PAD-US *file downloads* are Albers EPSG:5070, and the geodata model
docstring still says so. That is wrong for this path. The REST service is natively Web
Mercator and honours outSR, so we ask for EPSG:4326 and the server reprojects. Hence
source_srid = 4326 and the framework's reprojection step is a deliberate no-op here.


Why source_id is synthesized
----------------------------
PAD-US has no stable unique identifier. Two candidate fields are dead on arrival --
verified against the live service, not assumed:

    BndryID   the literal string "Not Applicable" for every row
    ST_Name   likewise "Not Applicable"; exactly one distinct value nationally

That leaves OBJECTID, which ArcGIS does not guarantee across service republishes. Keying
on it would mean a new PAD-US release silently renumbers everything and the upsert either
duplicates rows or updates the wrong ones.

So we hash stable attributes plus a coarsely rounded centroid:

    Unit_Nm | DesTp_Desc | MngNm_Desc | centroid x | centroid y

Deliberately NOT hashing the full geometry. PAD-US re-digitizes and simplifies boundaries
between releases, so a geometry hash would mint a fresh ID for the same real parcel and
orphan the old row. It would also be coordinate-dependent, so changing outSR would rotate
every ID in the table at once.

The centroid is computed AFTER reprojection to 4326, so the identifier does not depend on
which projection we happened to request.

CENTROID_PRECISION is the knob that matters. It trades two failure modes against each
other: too fine and a re-digitized boundary shifts the centroid enough to mint a new ID
(orphaning the old row); too coarse and two genuinely distinct neighbouring parcels
sharing a name, designation and manager collide into one. At 4 decimal places the
centroid is pinned to roughly 11 m, which absorbs ordinary boundary redrawing while
staying far finer than the distance between distinct parcels.
"""

import hashlib
import json
from collections.abc import Iterable, Iterator
from typing import Any

from django.contrib.gis.geos import GEOSGeometry

from geodata.models import PublicLand
from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.registry import register
from pipeline.aoi import AreaOfInterest
from pipeline.arcgis import ArcGisError, ArcGisFeatureClient, ArcGisResponseError

# The transport-level failures are the shared ArcGIS ones; aliased so callers of this
# module keep a PAD-US-flavoured name.
PadusError = ArcGisError
PadusResponseError = ArcGisResponseError


class UnknownPublicAccessCode(ArcGisError):
    """PAD-US returned a Pub_Access code we have no mapping for."""


# Verified against the live service: these four are the only distinct values nationally.
# An unmapped code is a real change upstream and must be mapped deliberately, never
# defaulted to UNKNOWN -- silently calling a new "closed" variant unknown would let the
# scoring model recommend somewhere illegal.
PUBLIC_ACCESS_CODES = {
    "OA": PublicLand.Access.OPEN,
    "RA": PublicLand.Access.RESTRICTED,
    "XA": PublicLand.Access.CLOSED,
    "UK": PublicLand.Access.UNKNOWN,
}


@register
class PadusAdapter(SourceAdapter):
    """Public land boundaries and legal access from PAD-US."""

    name = "padus"
    source = PublicLand.Source.PADUS
    model = PublicLand

    # We request outSR=4326, so nothing needs reprojecting on our side. See module docs.
    source_srid = AreaOfInterest.SRID

    # No tiling: the largest configured region (Maine) is ~7,900 polygons, which pages
    # comfortably. Tiling would add requests for no benefit.
    max_tile_degrees = None

    SERVICE_URL = (
        "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services"
        "/PADUS_Public_Access/FeatureServer/0/query"
    )

    # The layer advertises maxRecordCount 2000 but the service root says 1000. Take the
    # lower and never assume the server honoured it -- pagination advances by how many
    # features actually came back, not by what we asked for.
    page_size = 1000

    timeout_seconds = 120

    # Backstop so a server that always reports more data cannot spin forever.
    # 500 pages x 1000 is far beyond any configured region.
    max_pages = 500

    CENTROID_PRECISION = 4

    USER_AGENT = "CampSite-CIS454/0.1 (Syracuse University student project; TM05)"

    # --- fetch ------------------------------------------------------------------------

    def __init__(self, client: ArcGisFeatureClient | None = None):
        super().__init__()
        self.client = client or ArcGisFeatureClient(
            self.SERVICE_URL,
            page_size=self.page_size,
            max_pages=self.max_pages,
            timeout_seconds=self.timeout_seconds,
        )

    def fetch(self, aoi: AreaOfInterest):
        """Yield pages of GeoJSON features for `aoi`, paging via the shared client."""
        yield from self.client.iter_pages(aoi)

    # --- normalize --------------------------------------------------------------------

    def normalize(self, raw: Iterable[list[dict]]) -> Iterator[dict]:
        """Flatten pages into one record per feature, lazily."""
        for page in raw:
            for feature in page:
                yield self.to_record(feature)

    def to_record(self, feature: dict) -> dict:
        """One GeoJSON feature to one PublicLand field dict."""
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry")

        if not geometry:
            raise PadusResponseError(
                "PAD-US feature has no geometry "
                f"(OBJECTID {properties.get('OBJECTID')!r}, "
                f"Unit_Nm {properties.get('Unit_Nm')!r})"
            )

        geom = GEOSGeometry(json.dumps(geometry), srid=AreaOfInterest.SRID)

        # Polygon vs MultiPolygon is left alone on purpose: the service returns both, and
        # the framework promotes a single Polygon into the MultiPolygon column already.
        # Coercing here would duplicate a shared concern.

        return {
            "source_id": self.synthesize_source_id(geom, properties),
            "name": self._text(properties.get("Unit_Nm"), 255),
            "geom": geom,
            "manager": self._text(properties.get("MngNm_Desc"), 128),
            "designation": self._text(properties.get("DesTp_Desc"), 128),
            "public_access": self.map_public_access(properties),
            # GAP_Sts and MngTp_Desc ride along untouched. GAP status is a conservation
            # code, not an access code, and must never be read as one.
            "raw": properties,
        }

    def map_public_access(self, properties: dict) -> str:
        """Pub_Access code to a PublicLand.Access value, failing loudly on a new code."""
        code = (properties.get("Pub_Access") or "").strip().upper()
        try:
            return PUBLIC_ACCESS_CODES[code]
        except KeyError:
            raise UnknownPublicAccessCode(
                f"PAD-US returned Pub_Access={code!r} for "
                f"{properties.get('Unit_Nm')!r} (OBJECTID {properties.get('OBJECTID')!r}). "
                f"Known codes are {', '.join(sorted(PUBLIC_ACCESS_CODES))}. "
                "Map the new code deliberately rather than defaulting it -- guessing "
                "here could mark closed land as campable."
            ) from None

    def synthesize_source_id(self, geom: GEOSGeometry, properties: dict) -> str:
        """A stable identifier for a parcel that the source does not identify.

        See the module docstring for why this exists and why it excludes geometry.
        """
        centroid = geom.centroid
        precision = self.CENTROID_PRECISION
        parts = [
            (properties.get("Unit_Nm") or "").strip(),
            (properties.get("DesTp_Desc") or "").strip(),
            (properties.get("MngNm_Desc") or "").strip(),
            f"{centroid.x:.{precision}f}",
            f"{centroid.y:.{precision}f}",
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    @staticmethod
    def _text(value: Any, limit: int) -> str:
        """Trim to the column width so an unusually long name cannot fail the insert."""
        return (str(value).strip() if value is not None else "")[:limit]

    def run_parameters(self, aoi: AreaOfInterest) -> dict:
        parameters = super().run_parameters(aoi)
        parameters.update(service_url=self.SERVICE_URL, page_size=self.page_size)
        return parameters
