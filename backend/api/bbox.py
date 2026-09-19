"""
Bounding box parsing for map queries.

The wire format is `west,south,east,north` in EPSG:4326 decimal degrees -- the order
MapLibre's `map.getBounds().toArray().flat()` produces, and the same order GeoJSON itself
uses for its `bbox` member, so the frontend never has to reorder anything.

Every rejection here is a 400 with a specific reason. A malformed box is a client mistake
and should say so; it must never reach the database and surface as a 500.
"""


class InvalidBbox(ValueError):
    """The bbox parameter is missing, malformed, inverted, or out of range."""


def parse_bbox(raw: str | None) -> tuple[float, float, float, float]:
    """`"west,south,east,north"` to a validated tuple, or raise InvalidBbox."""
    if raw is None or not raw.strip():
        raise InvalidBbox(
            "The 'bbox' query parameter is required. "
            "Format: bbox=west,south,east,north in decimal degrees (EPSG:4326), "
            "for example bbox=-74.10,44.10,-74.05,44.15"
        )

    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 4:
        raise InvalidBbox(
            f"bbox needs exactly 4 comma-separated values (west,south,east,north), "
            f"got {len(parts)}: {raw!r}"
        )

    try:
        west, south, east, north = (float(part) for part in parts)
    except ValueError:
        raise InvalidBbox(f"bbox values must all be numbers, got {raw!r}") from None

    for label, value in (("west", west), ("east", east)):
        if not -180 <= value <= 180:
            raise InvalidBbox(f"bbox {label} longitude {value} is outside -180..180")
    for label, value in (("south", south), ("north", north)):
        if not -90 <= value <= 90:
            raise InvalidBbox(f"bbox {label} latitude {value} is outside -90..90")

    if west >= east:
        raise InvalidBbox(
            f"bbox west ({west}) must be less than east ({east}). "
            "The order is west,south,east,north."
        )
    if south >= north:
        raise InvalidBbox(
            f"bbox south ({south}) must be less than north ({north}). "
            "The order is west,south,east,north."
        )

    return west, south, east, north
