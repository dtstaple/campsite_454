"""
GPX export (TM05-79): a trail as a GPX 1.1 file a GPS unit or phone app can load.

    GET /api/routes/<osm_id>/gpx/[?campsites_within_m=500]
    GET /api/trails/<source_id>/gpx/[?campsites_within_m=500]   a clicked way's trail

The file is built from the same payload as the trail panel (routes.route_detail), so the
download always matches what the user was looking at:

  - one <trk> with one <trkseg>: the stitched route line. Its points are the line's own
    vertices plus the profile's sample points, so the track keeps the line's shape and the
    profile's elevation detail. <ele> is interpolated from the stored profile where it has
    one, and left out (it is optional in GPX) where it does not.
  - one <wpt> per campsite within the chosen distance, named with the display name.

GPX puts latitude first (`lat`, then `lon` attributes); GeoJSON puts longitude first. Every
coordinate here goes through `_point`, which takes (lon, lat) and writes them the GPX way.
Elements follow the order the GPX 1.1 schema requires (metadata, wpt*, rte*, trk*); the
tests validate the output against the schema (tests/fixtures/gpx-1.1.xsd).

Built with the standard library's ElementTree: writing GPX needs no dependency.
"""

import bisect
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime

from django.contrib.gis.geos import LineString

GPX_NS = "http://www.topografix.com/GPX/1/1"
SCHEMA_LOCATION = f"{GPX_NS} http://www.topografix.com/GPX/1/1/gpx.xsd"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
CREATOR = "CampSite"
CONTENT_TYPE = "application/gpx+xml"

ET.register_namespace("", GPX_NS)
ET.register_namespace("xsi", XSI_NS)


@dataclass(frozen=True)
class Waypoint:
    lon: float
    lat: float
    name: str
    desc: str | None = None
    sym: str | None = None
    type: str | None = None
    ele: float | None = None


def _tag(name: str) -> str:
    return f"{{{GPX_NS}}}{name}"


def _sub(parent: ET.Element, name: str, text: str | None = None, **attrs) -> ET.Element:
    element = ET.SubElement(parent, _tag(name), attrs)
    if text is not None:
        element.text = text
    return element


def _point(parent: ET.Element, name: str, lon: float, lat: float) -> ET.Element:
    """A wpt/trkpt: GPX order, latitude first."""
    return _sub(parent, name, lat=f"{lat:.6f}", lon=f"{lon:.6f}")


TrackPoint = tuple[float, float, float | None]


def track_points(line_m: LineString, distances, elevations) -> list[TrackPoint]:
    """(lon, lat, ele) along a METRIC_SRID line: its vertices and the profile's sample
    positions, in order, with elevation interpolated from the profile. `distances` and
    `elevations` are the profile's series (metres along the same stitched line), or None."""
    coords = line_m.coords
    vertex_at = [0.0]
    for (x0, y0), (x1, y1) in zip(coords, coords[1:], strict=False):
        vertex_at.append(vertex_at[-1] + ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
    # Scale to GEOS's length so sample distances and vertex distances agree exactly.
    scale = line_m.length / vertex_at[-1] if vertex_at[-1] else 1.0
    vertex_at = [d * scale for d in vertex_at]

    samples = list(distances or [])
    positions = sorted({round(d, 1) for d in vertex_at} | {round(d, 1) for d in samples})
    points = [line_m.interpolate(min(d, line_m.length)) for d in positions]
    lonlat = LineString(points, srid=line_m.srid).transform(4326, clone=True).coords
    if len(points) == 1:
        lonlat = lonlat[:1]

    heights = [_interpolate(samples, elevations, d) for d in positions] if samples else None
    return [(lon, lat, heights[i] if heights else None) for i, (lon, lat) in enumerate(lonlat)]


def _interpolate(distances, values, at: float) -> float | None:
    """Linear interpolation in a profile; None outside it."""
    if not distances or at < distances[0] - 0.5 or at > distances[-1] + 0.5:
        return None
    i = bisect.bisect_left(distances, at)
    if i == 0:
        return values[0]
    if i >= len(distances):
        return values[-1]
    d0, d1 = distances[i - 1], distances[i]
    v0, v1 = values[i - 1], values[i]
    if d1 == d0:
        return v1
    return v0 + (v1 - v0) * (at - d0) / (d1 - d0)


def build_gpx(
    name: str,
    track: list[TrackPoint],
    waypoints: list[Waypoint],
    desc: str | None = None,
    link: str | None = None,
    now: datetime | None = None,
) -> bytes:
    """The GPX 1.1 document, UTF-8 with an XML declaration."""
    root = ET.Element(
        _tag("gpx"),
        {"version": "1.1", "creator": CREATOR, f"{{{XSI_NS}}}schemaLocation": SCHEMA_LOCATION},
    )
    metadata = _sub(root, "metadata")
    _sub(metadata, "name", name)
    if desc:
        _sub(metadata, "desc", desc)
    if link:
        _sub(_sub(metadata, "link", href=link), "text", "CampSite")
    stamp = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    _sub(metadata, "time", stamp.isoformat().replace("+00:00", "Z"))
    lons = [p[0] for p in track] + [w.lon for w in waypoints]
    lats = [p[1] for p in track] + [w.lat for w in waypoints]
    if lons:
        _sub(
            metadata,
            "bounds",
            minlat=f"{min(lats):.6f}",
            minlon=f"{min(lons):.6f}",
            maxlat=f"{max(lats):.6f}",
            maxlon=f"{max(lons):.6f}",
        )

    for waypoint in waypoints:
        wpt = _point(root, "wpt", waypoint.lon, waypoint.lat)
        if waypoint.ele is not None:
            _sub(wpt, "ele", f"{waypoint.ele:.1f}")
        _sub(wpt, "name", waypoint.name)
        if waypoint.desc:
            _sub(wpt, "desc", waypoint.desc)
        if waypoint.sym:
            _sub(wpt, "sym", waypoint.sym)
        if waypoint.type:
            _sub(wpt, "type", waypoint.type)

    if track:
        trk = _sub(root, "trk")
        _sub(trk, "name", name)
        segment = _sub(trk, "trkseg")
        for lon, lat, ele in track:
            point = _point(segment, "trkpt", lon, lat)
            if ele is not None:
                _sub(point, "ele", f"{ele:.1f}")

    ET.indent(root, space=" ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def campsite_waypoints(items: list[dict]) -> list[Waypoint]:
    """The route detail's campsites as waypoints: display name, score and verdict."""
    waypoints = []
    for item in items:
        notes = []
        if item.get("score") is not None:
            notes.append(f"CampSite score {round(item['score'])}/100")
        legality = item.get("legality") or {}
        if legality.get("label"):
            notes.append(legality["label"])
        if item.get("position_label"):
            label = item["position_label"]
            notes.append(label[:1].upper() + label[1:])
        waypoints.append(
            Waypoint(
                lon=item["lon"],
                lat=item["lat"],
                name=item.get("display_name") or item.get("name") or "Campsite",
                desc=". ".join(notes) or None,
                sym="Campground",
                type="campsite",
            )
        )
    return waypoints


def filename(name: str) -> str:
    """A safe download name: "Van Hoevenberg Trail" -> "van-hoevenberg-trail.gpx"."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return f"{slug or 'trail'}.gpx"
