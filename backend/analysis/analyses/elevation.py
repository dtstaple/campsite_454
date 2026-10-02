"""
Elevation profiles for named routes, from USGS 3DEP (TM05-59).

Source, verified live 2026-10-02:

    POST https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/getSamples
         geometry={"points": [[lon, lat], ...], "spatialReference": {"wkid": 4326}}
         geometryType=esriGeometryMultipoint  returnFirstValueOnly=true
         interpolation=RSP_BilinearInterpolation  f=json
    -> {"samples": [{"location": {...}, "locationId": 17, "value": "1334.385375977",
                     "resolution": 1, "rasterId": 116579,
                     "attributes": {"Name": "NY_NH_Gaps_D24", "VerticalDatum": "NAVD 88", ...}}]}

A polyline request worked too, but a multipoint of points we place ourselves is what makes
the distance of every sample exact. All 455 points of the Van Hoevenberg Trail at 25 m
spacing came back from one request in ~1 s at 1 m (LiDAR) resolution. Samples arrive out
of order and are matched back by `locationId`. Values are metres, NAVD 88.

What is stored is the profile -- distance/elevation pairs and the statistics -- never
pixels. The cache key is the route geometry itself, so a re-ingested route whose geometry
changed gets a new profile and an unchanged one is never recomputed; terrain does not
change, so the TTL is a year.
"""

from __future__ import annotations

import json
from datetime import timedelta

import requests
from django.contrib.gis.geos import GEOSGeometry, LineString, MultiLineString, Point

from analysis.base import Analysis, AnalysisError, Computed
from geodata.models import METRIC_SRID
from pipeline.retry import call_with_backoff

THREEDEP_URL = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/getSamples"
)
BATCH_SIZE = 400
TIMEOUT_SECONDS = 60
#: Ends closer than this are treated as joined when stitching route members.
JOIN_TOLERANCE_M = 50.0

DEFAULTS = {
    "spacing_m": 25,
    # Smoothing and threshold were set from first principles before calibrating, not
    # fitted to the calibration route: a 100 m window is about the length of a
    # switchback leg, and 3 m is several times the vertical noise of 1 m LiDAR on a
    # rocky trail but well under any real climb. See docs/elevation.md.
    "smoothing_window_m": 100,
    "threshold_m": 3,
    "grade_window_m": 100,
}


# --- geometry ------------------------------------------------------------------------


def stitch(geom: GEOSGeometry) -> tuple[LineString, dict]:
    """One continuous, ordered line through a route's members.

    Merges touching members, then chains the merged parts end to end starting from the
    longest, attaching any part whose end is within JOIN_TOLERANCE_M of the chain's
    current start or end (reversing it if needed). Parts that never attach -- a parallel
    bypass whose ends meet the middle of the main line, or a disconnected stub -- are left
    out and counted, rather than drawn as a straight jump. Works in METRIC_SRID so the
    tolerance is metres.
    """
    projected = geom.transform(METRIC_SRID, clone=True)
    merged = projected.merged if isinstance(projected, MultiLineString) else projected
    parts = list(merged) if isinstance(merged, MultiLineString) else [merged]
    parts.sort(key=lambda part: part.length, reverse=True)

    chain = list(parts.pop(0).coords)
    joined, gaps = 1, []
    attached = True
    while parts and attached:
        attached = False
        start, end = Point(chain[0], srid=METRIC_SRID), Point(chain[-1], srid=METRIC_SRID)
        for index, part in enumerate(parts):
            head, tail = Point(part.coords[0]), Point(part.coords[-1])
            options = [
                (end.distance(head), "append", part.coords),
                (end.distance(tail), "append", part.coords[::-1]),
                (start.distance(tail), "prepend", part.coords),
                (start.distance(head), "prepend", part.coords[::-1]),
            ]
            gap, where, coords = min(options, key=lambda option: option[0])
            if gap <= JOIN_TOLERANCE_M:
                chain = chain + list(coords) if where == "append" else list(coords) + chain
                gaps.append(gap)
                joined += 1
                parts.pop(index)
                attached = True
                break

    line = LineString(chain, srid=METRIC_SRID)
    info = {
        "parts": joined + len(parts),
        "parts_used": joined,
        "parts_left_out": len(parts),
        "left_out_m": round(sum(part.length for part in parts), 1),
        "largest_join_gap_m": round(max(gaps), 1) if gaps else 0.0,
    }
    return line, info


def sample_points(line: LineString, spacing_m: float) -> tuple[list[float], list[Point]]:
    """Points every `spacing_m` along a METRIC_SRID line, plus its end. Returns
    (distances in metres, points in 4326)."""
    length = line.length
    distances = [i * spacing_m for i in range(int(length // spacing_m) + 1)]
    if length - distances[-1] > spacing_m / 4:
        distances.append(length)
    # Interpolate in metres, then reproject every sample in one call: building a GDAL
    # transformation costs ~14 ms, which per point was most of a profile's run time.
    coords = [line.interpolate(d).coords for d in distances]
    # A LineString needs two points; pad a single sample, and only read back what we have.
    projected = LineString(coords if len(coords) > 1 else coords * 2, srid=METRIC_SRID)
    projected.transform(4326)
    points = [Point(x, y, srid=4326) for x, y in projected.coords[: len(distances)]]
    return distances, points


# --- 3DEP ----------------------------------------------------------------------------


def post_samples(points: list[Point]) -> dict:
    payload = {
        "geometry": json.dumps(
            {"points": [[p.x, p.y] for p in points], "spatialReference": {"wkid": 4326}}
        ),
        "geometryType": "esriGeometryMultipoint",
        "returnFirstValueOnly": "true",
        "interpolation": "RSP_BilinearInterpolation",
        "outFields": "Name,VerticalDatum,AcquisitionDate",
        "f": "json",
    }

    def attempt():
        response = requests.post(THREEDEP_URL, data=payload, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise ValueError(f"3DEP error: {body['error']}")
        return body

    return call_with_backoff(
        attempt,
        retry_on=(requests.RequestException, ValueError),
        on_exhausted=lambda error: AnalysisError(f"3DEP getSamples failed: {error}"),
        max_attempts=3,
        backoff_seconds=2.0,
        describe="3DEP getSamples",
    )


def fetch_elevations(points: list[Point]) -> tuple[list[float | None], dict]:
    """Elevation in metres for each point, None where 3DEP has no data."""
    elevations: list[float | None] = [None] * len(points)
    datasets, resolutions = {}, set()
    for offset in range(0, len(points), BATCH_SIZE):
        batch = points[offset : offset + BATCH_SIZE]
        for sample in post_samples(batch).get("samples", []):
            index = offset + sample["locationId"]
            try:
                elevations[index] = float(sample["value"])
            except (TypeError, ValueError):
                continue  # "NoData"
            resolutions.add(sample.get("resolution"))
            attributes = sample.get("attributes") or {}
            if attributes.get("Name"):
                datasets[attributes["Name"]] = attributes.get("VerticalDatum")
    return elevations, {
        "datasets": sorted(datasets),
        "vertical_datum": sorted({d for d in datasets.values() if d}),
        "resolution_m": sorted(r for r in resolutions if r is not None),
    }


# --- statistics ----------------------------------------------------------------------


def fill_gaps(values: list[float | None]) -> list[float]:
    """Linear interpolation over None; ends take the nearest known value."""
    known = [i for i, v in enumerate(values) if v is not None]
    if not known:
        raise AnalysisError("no elevation data along the route")
    filled = list(values)
    for i in range(len(values)):
        if filled[i] is not None:
            continue
        before = max((k for k in known if k < i), default=None)
        after = min((k for k in known if k > i), default=None)
        if before is None:
            filled[i] = values[after]
        elif after is None:
            filled[i] = values[before]
        else:
            t = (i - before) / (after - before)
            filled[i] = values[before] + t * (values[after] - values[before])
    return filled


def smooth(values: list[float], window: int) -> list[float]:
    """Centred moving average over `window` samples (odd), shrinking at the ends."""
    half = max(0, window // 2)
    out = []
    for i in range(len(values)):
        lo, hi = max(0, i - half), min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def gain_loss(values: list[float], threshold_m: float) -> tuple[float, float]:
    """Total climb and descent, counting a change only once it exceeds `threshold_m`
    from the last counted point. A naive sum of every positive step counts sensor noise
    as climbing -- on 1 m LiDAR over a rocky trail that inflates gain badly."""
    gain = loss = 0.0
    reference = values[0]
    for value in values[1:]:
        change = value - reference
        if change >= threshold_m:
            gain += change
            reference = value
        elif change <= -threshold_m:
            loss -= change
            reference = value
    return gain, loss


def naive_gain_loss(values: list[float]) -> tuple[float, float]:
    """Every positive and negative step summed: the baseline gain_loss() improves on."""
    gain = sum(max(0.0, b - a) for a, b in zip(values, values[1:], strict=False))
    loss = sum(max(0.0, a - b) for a, b in zip(values, values[1:], strict=False))
    return gain, loss


def max_grade(distances: list[float], values: list[float], window_m: float):
    """Steepest grade over any stretch of at least `window_m`, as (percent, at metres).
    Measured over a stretch, not between adjacent samples, so one noisy sample cannot
    produce a 60% "grade"."""
    best, at, j = 0.0, 0.0, 0
    for i in range(len(distances)):
        while j < len(distances) and distances[j] - distances[i] < window_m:
            j += 1
        if j >= len(distances):
            break
        run = distances[j] - distances[i]
        grade = abs(values[j] - values[i]) / run * 100
        if grade > best:
            best, at = grade, distances[i]
    return best, at


def profile_stats(distances, elevations, params) -> dict:
    spacing = params["spacing_m"]
    window = max(1, round(params["smoothing_window_m"] / spacing)) | 1  # odd
    smoothed = smooth(elevations, window)
    gain, loss = gain_loss(smoothed, params["threshold_m"])
    naive_gain, naive_loss = naive_gain_loss(elevations)
    grade, grade_at = max_grade(distances, smoothed, params["grade_window_m"])
    high = max(range(len(smoothed)), key=lambda i: smoothed[i])
    low = min(range(len(smoothed)), key=lambda i: smoothed[i])
    return {
        "length_m": round(distances[-1], 1),
        "gain_m": round(gain, 1),
        "loss_m": round(loss, 1),
        "high_m": round(smoothed[high], 1),
        "high_at_m": round(distances[high], 1),
        "low_m": round(smoothed[low], 1),
        "low_at_m": round(distances[low], 1),
        "start_m": round(smoothed[0], 1),
        "end_m": round(smoothed[-1], 1),
        "max_grade_pct": round(grade, 1),
        "max_grade_at_m": round(grade_at, 1),
        "naive_gain_m": round(naive_gain, 1),
        "naive_loss_m": round(naive_loss, 1),
    }


# --- the analysis --------------------------------------------------------------------


class RouteProfile(Analysis):
    name = "route_profile"
    version = "1"
    ttl = timedelta(days=365)
    grid_degrees = None

    def compute(self, geom, window, params):
        settings = {**DEFAULTS, **params}
        line, path = stitch(geom)
        if line.length < settings["spacing_m"]:
            raise AnalysisError("route is shorter than one sample spacing")
        distances, points = sample_points(line, settings["spacing_m"])
        raw, source = fetch_elevations(points)
        nodata = sum(1 for value in raw if value is None)
        elevations = fill_gaps(raw)
        stats = profile_stats(distances, elevations, settings)

        # The stitched path in 4326, for the map and the 3D camera to follow.
        line_4326 = line.transform(4326, clone=True)
        value = {
            "stats": stats,
            "distance_m": [round(d, 1) for d in distances],
            "elevation_m": [round(e, 1) for e in elevations],
            "path": path,
            "line": [[round(x, 6), round(y, 6)] for x, y in line_4326.coords],
            "params": settings,
        }
        provenance = {
            "source": "usgs-3dep",
            "url": THREEDEP_URL,
            "sample_count": len(points),
            "nodata_count": nodata,
            **source,
        }
        return Computed(value, provenance)
