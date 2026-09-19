"""
Areas of interest: the "where" every ingestion run is scoped to.

An AreaOfInterest is a value object, not a model. Regions are configuration (see
regions.yml), not data, so they live in a file under version control rather than in a
table someone has to seed.

The CRS is deliberately NOT a field. Every bbox here is EPSG:4326, fixed by contract as
the class constant SRID. Making it configurable would put projection variance in two
places -- here and in each adapter's declared source_srid -- and a typo in the config
would then skew every spatial query silently instead of failing loudly. Adapters are
where projection differences belong, because that is where they actually originate.
"""

import math
from collections.abc import Iterator
from dataclasses import dataclass, replace

from django.contrib.gis.geos import Polygon


class InvalidAreaOfInterest(ValueError):
    """A bounding box is malformed, inverted, or outside valid lon/lat range."""


@dataclass(frozen=True)
class AreaOfInterest:
    """A named bounding box in EPSG:4326.

    Attributes:
        name: Config key and the value written to IngestRun.region, e.g. "adirondacks".
        label: Human-readable name for logs and the UI, e.g. "Adirondack Park".
        bbox: (min_lon, min_lat, max_lon, max_lat) in decimal degrees.
        states: Postal codes this area covers. PAD-US and NHD are distributed per
            state, so adapters use this to decide which extracts to pull.
        notes: Anything a future adapter author needs to know -- sparse coverage,
            unusually large extents, source quirks.
    """

    SRID = 4326

    name: str
    label: str
    bbox: tuple[float, float, float, float]
    states: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self):
        if len(self.bbox) != 4:
            raise InvalidAreaOfInterest(
                f"{self.name}: bbox needs 4 values (min_lon, min_lat, max_lon, max_lat), "
                f"got {len(self.bbox)}"
            )

        min_lon, min_lat, max_lon, max_lat = self.bbox

        if not -180 <= min_lon <= 180 or not -180 <= max_lon <= 180:
            raise InvalidAreaOfInterest(
                f"{self.name}: longitude out of range in {self.bbox} (expected -180..180)"
            )
        if not -90 <= min_lat <= 90 or not -90 <= max_lat <= 90:
            raise InvalidAreaOfInterest(
                f"{self.name}: latitude out of range in {self.bbox} (expected -90..90)"
            )
        if min_lon >= max_lon:
            raise InvalidAreaOfInterest(
                f"{self.name}: min_lon {min_lon} must be less than max_lon {max_lon}. "
                "Bbox order is (min_lon, min_lat, max_lon, max_lat)."
            )
        if min_lat >= max_lat:
            raise InvalidAreaOfInterest(
                f"{self.name}: min_lat {min_lat} must be less than max_lat {max_lat}. "
                "Bbox order is (min_lon, min_lat, max_lon, max_lat)."
            )

    @property
    def min_lon(self) -> float:
        return self.bbox[0]

    @property
    def min_lat(self) -> float:
        return self.bbox[1]

    @property
    def max_lon(self) -> float:
        return self.bbox[2]

    @property
    def max_lat(self) -> float:
        return self.bbox[3]

    def as_polygon(self) -> Polygon:
        """The bbox as a GEOS polygon, ready to hand to a spatial query."""
        poly = Polygon.from_bbox(self.bbox)
        poly.srid = self.SRID
        return poly

    def tile(self, max_degrees: float) -> Iterator["AreaOfInterest"]:
        """Split into a grid of sub-areas, none wider or taller than max_degrees.

        Used by adapters whose source cannot handle a whole region in one request --
        deep ArcGIS paging, or an Overpass query that would time out. The tiles cover
        exactly the same ground as the original with no gaps and no overlap: the outer
        edges are snapped back to the original bounds so floating-point drift cannot
        open a seam between adjacent tiles.

        Yields self unchanged when the area already fits, so callers do not need to
        special-case small regions.
        """
        if max_degrees <= 0:
            raise InvalidAreaOfInterest(
                f"{self.name}: max_degrees must be positive, got {max_degrees}"
            )

        min_lon, min_lat, max_lon, max_lat = self.bbox
        width = max_lon - min_lon
        height = max_lat - min_lat

        # Round before ceil so 2.1 / 0.7 counts as 3 tiles rather than 4.
        columns = max(1, math.ceil(round(width / max_degrees, 9)))
        rows = max(1, math.ceil(round(height / max_degrees, 9)))

        if columns == 1 and rows == 1:
            yield self
            return

        lons = [min_lon + i * width / columns for i in range(columns + 1)]
        lats = [min_lat + j * height / rows for j in range(rows + 1)]
        lons[-1] = max_lon
        lats[-1] = max_lat

        for j in range(rows):
            for i in range(columns):
                yield replace(
                    self,
                    name=f"{self.name}/tile-{i}-{j}",
                    bbox=(lons[i], lats[j], lons[i + 1], lats[j + 1]),
                )

    def as_overpass_bbox(self) -> str:
        """Overpass and several other APIs want (min_lat, min_lon, max_lat, max_lon)."""
        return f"{self.min_lat},{self.min_lon},{self.max_lat},{self.max_lon}"

    def __str__(self):
        return f"{self.label} ({self.name})"
