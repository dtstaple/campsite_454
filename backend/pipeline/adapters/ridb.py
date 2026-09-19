"""
RIDB adapter: individual campsites from Recreation.gov.

Everything below was verified against the live API, because the research phase could not
reach rendered documentation and several published assumptions turned out to be wrong.

Service shape
-------------
    GET /facilities?latitude&longitude&radius&limit&offset   -> campgrounds near a point
    GET /facilities/{FacilityID}/campsites?limit&offset       -> sites inside one

The key travels in an `apikey` request header, read from the RIDB_API_KEY environment
variable. It is never logged, never written into IngestRun.parameters, and never appears
in an error message -- the terms of use forbid disclosing it.

Radius is the whole design constraint
-------------------------------------
`radius` is in **miles and hard-capped at 25**: asking for 30, 40 or 1000 returns exactly
the same result set as 25, and the farthest facility returned at radius=25 sits at 25.0
miles. So a single query cannot cover any of our regions -- the Adirondacks alone are
roughly 104 by 131 miles, needing a circumscribing radius of about 84.

Tiling is therefore mandatory rather than an optimisation. At 0.5 degrees a tile is about
34.5 by 24.9 miles at Adirondack latitude, whose circumscribing circle has a radius of
21.3 miles -- inside the 25 cap with roughly 15% margin, and still inside it at Maine's
northern edge.

Circles do not tile
-------------------
Every other source takes a bounding box; this one takes a circle. A circle that covers a
square tile also covers about 27% more ground outside it, so results arrive that belong
to a neighbouring tile. Those are filtered back to the tile's bounding box in normalize.

Nothing is lost by filtering: the tiles cover the region exactly, so a site dropped by one
tile is returned and kept by the tile it actually falls in. Keeping them instead would
make IngestRun.region a lie -- rows attributed to a region they sit outside.

The framework offers no hook for this, and rightly so: spatial filtering is only needed by
sources whose query shape does not match the area shape. fetch() therefore passes the tile
alongside its results, which the streaming contract already allows.
"""

import os
from collections.abc import Iterable, Iterator

import requests
from django.contrib.gis.geos import Point

from geodata.models import Campsite
from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.registry import register
from pipeline.aoi import AreaOfInterest
from pipeline.retry import call_with_backoff

RIDB_BASE_URL = "https://ridb.recreation.gov/api/v1"

# Verified live: values above this are silently clamped rather than rejected.
MAX_RADIUS_MILES = 25

USER_AGENT = "CampSite-CIS454/0.1 (Syracuse University student project; TM05)"


class RidbError(Exception):
    """Base for every failure this adapter raises."""


class RidbAuthError(RidbError):
    """The API key is missing, wrong, or no longer accepted."""


class RidbUnavailable(RidbError):
    """Transient: rate limited or a server error. Retried, then given up on."""


class RidbResponseError(RidbError):
    """Permanent: the response is not the shape this adapter can read."""


# CampsiteType is free text from the reservation system. These rules are applied in
# order, first match wins, and anything unmatched is honestly UNKNOWN rather than forced
# into a category. Observed values include STANDARD NONELECTRIC, TENT ONLY NONELECTRIC,
# WALK TO, GROUP SHELTER NONELECTRIC, CABIN NONELECTRIC and MANAGEMENT.
SITE_TYPE_RULES = (
    # GROUP is checked before SHELTER so "GROUP SHELTER" lands in the right bucket.
    ("GROUP", Campsite.SiteType.GROUP),
    ("SHELTER", Campsite.SiteType.LEAN_TO),
    # Walk-in, hike-in and boat-in sites are designated but reached on foot or water,
    # which is what "primitive" means for scoring purposes.
    ("WALK", Campsite.SiteType.PRIMITIVE),
    ("HIKE", Campsite.SiteType.PRIMITIVE),
    ("BOAT", Campsite.SiteType.PRIMITIVE),
    # Administrative entries in the reservation system, not places anyone may camp.
    # Mapped to UNKNOWN rather than dropped, so scoring can exclude them explicitly.
    ("MANAGEMENT", Campsite.SiteType.UNKNOWN),
    ("STANDARD", Campsite.SiteType.DESIGNATED),
    ("TENT", Campsite.SiteType.DESIGNATED),
    ("RV", Campsite.SiteType.DESIGNATED),
    ("CABIN", Campsite.SiteType.DESIGNATED),
    ("ELECTRIC", Campsite.SiteType.DESIGNATED),
)

CAPACITY_ATTRIBUTE = "Max Num of People"


class RidbClient:
    """Thin authenticated JSON client for RIDB, with backoff on transient failures."""

    RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        base_url: str = RIDB_BASE_URL,
        api_key: str | None = None,
        timeout_seconds: int = 60,
        max_attempts: int = 4,
        backoff_seconds: float = 5.0,
        sleep=None,
    ):
        self.base_url = base_url
        # Read at construction so a missing key fails before any request is attempted.
        self._api_key = api_key if api_key is not None else os.environ.get("RIDB_API_KEY", "")
        if not self._api_key:
            raise RidbAuthError(
                "RIDB_API_KEY is not set. Add it to the repo-root .env (it is gitignored) "
                "and register for a free key at https://ridb.recreation.gov/profile."
            )
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._session = requests.Session()
        self._session.headers.update({"apikey": self._api_key, "User-Agent": USER_AGENT})

    def get(self, path: str, params: dict) -> dict:
        kwargs = {}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        return call_with_backoff(
            lambda: self._attempt(path, params),
            retry_on=RidbUnavailable,
            on_exhausted=lambda last: RidbUnavailable(
                f"RIDB still unavailable after {self.max_attempts} attempts. The service "
                f"publishes no rate-limit headers, so back off generously. Last: {last}"
            ),
            max_attempts=self.max_attempts,
            backoff_seconds=self.backoff_seconds,
            describe=f"RIDB {path}",
            **kwargs,
        )

    def _attempt(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.get(url, params=params, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise RidbUnavailable(f"request to {path} failed: {exc}") from exc

        if response.status_code in (401, 403):
            # Deliberately does not echo the key or any part of it.
            raise RidbAuthError(
                f"RIDB rejected the API key with HTTP {response.status_code} on {path}. "
                "Check RIDB_API_KEY in .env is current and has not been revoked."
            )

        if response.status_code in self.RETRYABLE_STATUSES:
            raise RidbUnavailable(f"HTTP {response.status_code} from {path}")

        if response.status_code != 200:
            raise RidbResponseError(
                f"RIDB returned HTTP {response.status_code} on {path}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RidbResponseError(
                f"RIDB returned non-JSON on {path}: {response.text[:200]}"
            ) from exc

        if not isinstance(payload, dict) or "RECDATA" not in payload:
            raise RidbResponseError(
                f"RIDB response for {path} has no RECDATA; got "
                f"{sorted(payload) if isinstance(payload, dict) else type(payload).__name__}"
            )
        return payload

    def iter_records(self, path: str, params: dict, page_size: int = 50) -> Iterator[dict]:
        """Yield every record from a paged RIDB collection."""
        offset = 0
        while True:
            payload = self.get(path, {**params, "limit": page_size, "offset": offset})
            records = payload.get("RECDATA") or []
            if not records:
                return
            yield from records

            offset += len(records)
            total = ((payload.get("METADATA") or {}).get("RESULTS") or {}).get("TOTAL_COUNT")
            if total is None or offset >= total:
                return


@register
class RidbAdapter(SourceAdapter):
    """Individual campsites from Recreation.gov.

    One row is one campsite, not one campground. The Campsite model is a PointField
    documented as "one spot", and a campground is an area holding dozens of them. Sites
    also carry the attributes scoring needs -- type, reservability, capacity -- which a
    campground record does not.

    The cost is one extra request per campground. That stays modest because only about a
    quarter of RIDB facilities are campgrounds: 21 of 77 within 25 miles of the White
    Mountains. Facilities that are not campgrounds are skipped before any site request.
    """

    name = "ridb"
    source = Campsite.Source.RIDB
    model = Campsite
    source_srid = AreaOfInterest.SRID

    # Not tunable in the usual sense -- forced by the 25 mile radius cap. See module docs.
    max_tile_degrees = 0.5

    page_size = 50
    facility_type = "Campground"

    def __init__(self, client: RidbClient | None = None):
        super().__init__()
        self.client = client or RidbClient()

    # --- fetch ------------------------------------------------------------------------

    @staticmethod
    def search_circle(aoi: AreaOfInterest) -> tuple[float, float, int]:
        """The centre and radius of a circle covering `aoi`, capped at the API maximum.

        Returned radius is always MAX_RADIUS_MILES: asking for less would risk clipping a
        tile corner, and asking for more is silently clamped anyway.
        """
        centre_lon = (aoi.min_lon + aoi.max_lon) / 2
        centre_lat = (aoi.min_lat + aoi.max_lat) / 2
        return centre_lat, centre_lon, MAX_RADIUS_MILES

    def fetch(self, aoi: AreaOfInterest) -> Iterator[tuple[AreaOfInterest, dict, list[dict]]]:
        """Yield (tile, facility, campsites) so normalize can filter back to the tile."""
        latitude, longitude, radius = self.search_circle(aoi)

        for facility in self.client.iter_records(
            "/facilities",
            {"latitude": latitude, "longitude": longitude, "radius": radius},
            page_size=self.page_size,
        ):
            if facility.get("FacilityTypeDescription") != self.facility_type:
                continue

            facility_id = facility.get("FacilityID")
            if not facility_id:
                continue

            campsites = list(
                self.client.iter_records(
                    f"/facilities/{facility_id}/campsites", {}, page_size=self.page_size
                )
            )
            if campsites:
                yield aoi, facility, campsites

    # --- normalize --------------------------------------------------------------------

    def normalize(self, raw: Iterable[tuple[AreaOfInterest, dict, list[dict]]]) -> Iterator[dict]:
        for aoi, facility, campsites in raw:
            for site in campsites:
                record = self.to_record(site, facility, aoi)
                if record is not None:
                    yield record

    def to_record(self, site: dict, facility: dict, aoi: AreaOfInterest) -> dict | None:
        """One campsite to one Campsite field dict, or None if it belongs to another tile."""
        latitude = site.get("CampsiteLatitude")
        longitude = site.get("CampsiteLongitude")

        base = {
            "source_id": f"campsite/{site.get('CampsiteID')}",
            "name": (site.get("CampsiteName") or "").strip()[:255],
            "site_type": self.site_type_for(site),
            "reservable": self.reservable_for(site),
            "capacity": self.capacity_for(site),
            "raw": {"campsite": site, "facility_id": facility.get("FacilityID")},
        }

        # RIDB warns that some coordinates are blank, and it also publishes 0/0 -- which
        # is a point in the Gulf of Guinea, not a campsite. Emitting the record without
        # geometry lets the framework skip it and count it in IngestRun.notes, rather
        # than dropping it silently or storing a fictional location.
        if not latitude or not longitude:
            return {**base, "geom": None}

        # Drop what the over-wide search circle pulled in from a neighbouring tile; that
        # tile returns and keeps it.
        if not self.within(aoi, float(longitude), float(latitude)):
            return None

        return {**base, "geom": Point(float(longitude), float(latitude), srid=AreaOfInterest.SRID)}

    @staticmethod
    def within(aoi: AreaOfInterest, longitude: float, latitude: float) -> bool:
        """Inclusive bounds, so a site on a shared tile edge is never lost by both."""
        return aoi.min_lon <= longitude <= aoi.max_lon and aoi.min_lat <= latitude <= aoi.max_lat

    @staticmethod
    def site_type_for(site: dict) -> str:
        campsite_type = (site.get("CampsiteType") or "").upper()
        for token, mapped in SITE_TYPE_RULES:
            if token in campsite_type:
                return mapped
        return Campsite.SiteType.UNKNOWN

    @staticmethod
    def reservable_for(site: dict) -> bool | None:
        """CampsiteReservable is a real boolean; absence means unknown, not False."""
        value = site.get("CampsiteReservable")
        return value if isinstance(value, bool) else None

    @staticmethod
    def capacity_for(site: dict) -> int | None:
        """Capacity lives in ATTRIBUTES, not as a column, and is often absent."""
        for attribute in site.get("ATTRIBUTES") or []:
            if attribute.get("AttributeName") == CAPACITY_ATTRIBUTE:
                try:
                    capacity = int(str(attribute.get("AttributeValue")).strip())
                except (TypeError, ValueError):
                    return None
                return capacity if capacity > 0 else None
        return None

    def run_parameters(self, aoi: AreaOfInterest) -> dict:
        parameters = super().run_parameters(aoi)
        # Note the absence of anything key-derived.
        parameters.update(
            base_url=self.client.base_url,
            radius_miles=MAX_RADIUS_MILES,
            facility_type=self.facility_type,
            max_tile_degrees=self.max_tile_degrees,
        )
        return parameters
