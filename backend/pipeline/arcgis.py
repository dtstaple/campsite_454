"""
Paged ArcGIS REST feature query client.

Two of our sources are ArcGIS services -- PAD-US on ArcGIS Online and USGS NHD on a
MapServer -- and a third variant of the same paging loop would be exactly the copy-paste
the framework exists to prevent. The conversation is identical; only the URL, the filter
and the field names differ.

Two quirks are handled here rather than in each adapter, because both are easy to get
silently wrong:

* ArcGIS reports query errors in a **200** body as {"error": {...}} rather than using an
  HTTP status. Code that only checks status codes treats that as a successful empty page.

* `exceededTransferLimit` moves. PAD-US (ArcGIS Online) puts it inside "properties";
  NHD (MapServer) puts it at the top level. Both are checked, so neither service needs to
  declare where its flag lives.

Pagination advances by the number of features that actually arrived, never by the page
size requested, because a service is free to return fewer than asked for.
"""

import logging
from collections.abc import Iterator

import requests

from pipeline.aoi import AreaOfInterest

logger = logging.getLogger(__name__)

USER_AGENT = "CampSite-CIS454/0.1 (Syracuse University student project; TM05)"


class ArcGisError(Exception):
    """Base for every failure this client raises."""


class ArcGisResponseError(ArcGisError):
    """The service was unreachable, errored, or returned something unusable."""


class ArcGisFeatureClient:
    """Pages GeoJSON features out of one ArcGIS feature or map service layer."""

    def __init__(
        self,
        service_url: str,
        *,
        page_size: int = 1000,
        max_pages: int = 500,
        timeout_seconds: int = 120,
        user_agent: str = USER_AGENT,
    ):
        self.service_url = service_url
        self.page_size = page_size
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent

    def iter_pages(
        self,
        aoi: AreaOfInterest,
        *,
        where: str = "1=1",
        out_fields: str = "*",
    ) -> Iterator[list[dict]]:
        """Yield pages of GeoJSON features intersecting `aoi`.

        A generator, so the framework writes batches to the database while later pages
        are still in flight rather than accumulating a whole region in memory.
        """
        offset = 0
        for _ in range(self.max_pages):
            payload = self.request_page(aoi, offset, where=where, out_fields=out_fields)

            features = payload.get("features")
            if features is None:
                raise ArcGisResponseError(
                    f"{self.service_url} response at offset {offset} has no 'features' "
                    f"key; got keys {sorted(payload)}"
                )

            # An empty page means the end, whatever the transfer-limit flag claims.
            if not features:
                return

            yield features

            offset += len(features)

            if not self._more_to_come(payload):
                return

        raise ArcGisResponseError(
            f"{self.service_url} still reported more data after {self.max_pages} pages "
            f"({self.max_pages * self.page_size} records). Refusing to loop further."
        )

    @staticmethod
    def _more_to_come(payload: dict) -> bool:
        """True when the service says it truncated this page.

        Checked in both documented locations: top level (MapServer, e.g. NHD) and inside
        "properties" (ArcGIS Online, e.g. PAD-US). A service that omits the flag entirely
        on the final page is therefore correctly read as finished.
        """
        if payload.get("exceededTransferLimit"):
            return True
        properties = payload.get("properties") or {}
        return bool(properties.get("exceededTransferLimit"))

    def query_params(
        self, aoi: AreaOfInterest, offset: int, *, where: str, out_fields: str
    ) -> dict:
        return {
            "geometry": ",".join(str(coordinate) for coordinate in aoi.bbox),
            "geometryType": "esriGeometryEnvelope",
            "inSR": AreaOfInterest.SRID,
            "outSR": AreaOfInterest.SRID,
            "spatialRel": "esriSpatialRelIntersects",
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true",
            "resultOffset": offset,
            "resultRecordCount": self.page_size,
            "f": "geojson",
        }

    def request_page(
        self, aoi: AreaOfInterest, offset: int, *, where: str = "1=1", out_fields: str = "*"
    ) -> dict:
        params = self.query_params(aoi, offset, where=where, out_fields=out_fields)

        try:
            response = self._session.get(
                self.service_url, params=params, timeout=self.timeout_seconds
            )
        except requests.RequestException as exc:
            raise ArcGisResponseError(
                f"request failed at offset {offset} for {aoi.name}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise ArcGisResponseError(
                f"{self.service_url} returned HTTP {response.status_code} at offset "
                f"{offset} for {aoi.name}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ArcGisResponseError(
                f"{self.service_url} returned non-JSON at offset {offset} for "
                f"{aoi.name}: {response.text[:200]}"
            ) from exc

        # ArcGIS reports query errors in a 200 body rather than an HTTP status.
        if isinstance(payload, dict) and "error" in payload:
            raise ArcGisResponseError(
                f"{self.service_url} error at offset {offset} for {aoi.name}: "
                f"{payload['error']}"
            )

        return payload


def case_insensitive(properties: dict) -> dict:
    """Lower-case every key once, so field case stops mattering.

    NHD returns lowercase field names on the flowline layer and UPPERCASE on the
    waterbody layer -- same service, same release. Looking up the wrong case yields None
    rather than an error, which would quietly write null names and null fcodes into the
    database. Normalising once at the boundary makes that class of bug impossible.
    """
    return {key.lower(): value for key, value in properties.items()}
