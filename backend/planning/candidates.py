"""
Potential campsites along a trail (TM05-99): computed spots, not mapped ones.

Hikers want to know where they *could* camp, not only where someone has mapped a site. A
candidate is a point that passes every hard filter of NY's rules for camping away from a
designated site. It is then scored with the same engine as a mapped campsite.

    1. Sample. Stations every `sample_spacing_m` along the stitched route line, and points
       offset to each side of it at `offsets_m`, kept inside the user's corridor.
    2. Hard filters, cheapest first. A point is counted against the first one it fails:
         public_land   inside public land whose (most restrictive) access is open
         trail         at least 150 ft from any mapped trail
         water         at least 150 ft from any mapped water
         elevation     clear of the DEC elevation limits (TM05-76) by their margin
         terrain       3DEP elevation and slope available (counted with the elevation
                       sample, too, when 3DEP has no value there)
         slope         at or below `max_slope_deg`
    3. Score the survivors with the scoring engine: the flattest at each station, at most
       `max_scored`. Weather is left out: it is tonight's forecast, and this answer is
       cached for weeks.
    4. Spread: highest score first, each at least `min_spacing_m` (about 0.5 mi) along the
       trail from the ones kept, at most `max_results`. Returned in mile order.

Everything is measured in METRIC_SRID metres. The trail and water checks are indexed
ST_DWithin queries on `geom_m`. The answer, not the samples, is cached in the analysis
cache, keyed by the route geometry, the corridor and this module's config.

What is not checked, and the response says so on every candidate: distance from roads
(roads are not in the data), private inholdings PAD-US misses, and current local rules.
A candidate is "Potential spot (unverified)" and nothing more.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import replace
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import yaml
from django.contrib.gis.geos import GEOSGeometry, LineString, MultiPoint, Point
from django.db import connection

from analysis.analyses import elevation
from analysis.analyses.elevation import stitch
from analysis.analyses.terrain import SiteTerrain
from analysis.base import Analysis, AnalysisError, Computed
from geodata.confidence import computed_payload
from geodata.models import METRIC_SRID
from scoring.config import load as load_scoring_config
from scoring.engine import score_location
from scoring.factors import ACCESS_STRICTNESS
from scoring.verdict import ELEVATION_MARGIN_FT, FT_PER_M, RULES, elevation_limits

CONFIG_PATH = Path(__file__).with_name("candidates.yml")

LABEL = "Potential spot (unverified)"
ROAD_NOTE = "Road distance isn't checked; verify current rules on the ground."
FILTERS = ["public_land", "trail", "water", "elevation", "terrain", "slope"]


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def config_digest(settings: dict) -> str:
    raw = json.dumps(settings, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# --- 1. sampling ---------------------------------------------------------------------------


def sample_points(line_m: LineString, within_m: float, settings: dict) -> list[dict]:
    """Stations along the line and points either side of it, in metres. Each sample says
    where it came from: its station's distance along, its side, and its offset."""
    length = line_m.length
    spacing = float(settings["sample_spacing_m"])
    offsets = [float(o) for o in settings["offsets_m"] if float(o) <= within_m]
    samples = []
    stations = int(length // spacing) + 1
    for station in range(stations):
        along = min(station * spacing + spacing / 2, length)
        a = line_m.interpolate(max(along - 5, 0))
        b = line_m.interpolate(min(along + 5, length))
        dx, dy = b.x - a.x, b.y - a.y
        norm = math.hypot(dx, dy)
        if norm == 0:
            continue
        # Unit normal to the left of the direction of travel.
        nx, ny = -dy / norm, dx / norm
        centre = line_m.interpolate(along)
        for side, sign in (("left", 1), ("right", -1)):
            for offset in offsets:
                samples.append(
                    {
                        "x": centre.x + sign * nx * offset,
                        "y": centre.y + sign * ny * offset,
                        "station_along_m": along,
                        "side": side,
                        "offset_m": offset,
                    }
                )
    return samples


# --- 2. hard filters -----------------------------------------------------------------------

POINTS_CTE = """
WITH pts AS (
    SELECT u.i, ST_SetSRID(ST_MakePoint(u.x, u.y), %s) AS g
    FROM unnest(%s::int[], %s::float8[], %s::float8[]) AS u(i, x, y)
)
"""


def _query(sql: str, samples: list[dict], indices: list[int], *extra) -> list[tuple]:
    xs = [samples[i]["x"] for i in indices]
    ys = [samples[i]["y"] for i in indices]
    with connection.cursor() as cursor:
        cursor.execute(POINTS_CTE + sql, [METRIC_SRID, indices, xs, ys, *extra])
        return cursor.fetchall()


def public_land(samples: list[dict], indices: list[int]) -> dict[int, dict]:
    """For points inside public land: the most restrictive access of the parcels there,
    every parcel's designation, name and manager (for the High Peaks rule), and one name
    to show."""
    rows = _query(
        """
        SELECT pts.i, array_agg(p.public_access),
               string_agg(concat_ws(' ', p.designation, p.name, p.manager), ' | '),
               min(coalesce(nullif(p.name, ''), nullif(p.designation, ''), 'public land'))
        FROM pts JOIN geodata_publicland p ON ST_Intersects(p.geom, ST_Transform(pts.g, 4326))
        GROUP BY pts.i
        """,
        samples,
        indices,
    )
    out = {}
    for index, accesses, names, display in rows:
        access = min(
            accesses,
            key=lambda value: ACCESS_STRICTNESS.index(value)
            if value in ACCESS_STRICTNESS
            else ACCESS_STRICTNESS.index("unknown"),
        )
        out[index] = {"access": access, "names": names or "", "display": display}
    return out


def near(table: str, samples: list[dict], indices: list[int], distance_m: float) -> set[int]:
    """The points within `distance_m` of any row of `table` (indexed, metric)."""
    rows = _query(
        f"""
        SELECT pts.i FROM pts
        WHERE EXISTS (SELECT 1 FROM {table} t WHERE ST_DWithin(t.geom_m, pts.g, %s))
        """,
        samples,
        indices,
        distance_m,
    )
    return {row[0] for row in rows}


def nearest_m(table: str, x: float, y: float) -> float | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT ST_Distance(t.geom_m, p.g)
            FROM {table} t, (SELECT ST_SetSRID(ST_MakePoint(%s, %s), %s) AS g) p
            ORDER BY t.geom_m <-> p.g LIMIT 1
            """,
            [x, y, METRIC_SRID],
        )
        row = cursor.fetchone()
    return round(row[0], 1) if row else None


def to_wgs84(samples: list[dict], indices: list[int]) -> dict[int, Point]:
    if not indices:
        return {}
    points = MultiPoint(
        [Point(samples[i]["x"], samples[i]["y"]) for i in indices], srid=METRIC_SRID
    )
    points.transform(4326)
    return {i: Point(p.x, p.y, srid=4326) for i, p in zip(indices, points, strict=True)}


def elevation_check(point: Point, elevation_m: float, land_names: str) -> tuple[bool, str]:
    """Whether the point is clear of every DEC elevation limit by the verdict's margin,
    and how that reads. An unsaved stand-in site: never a lean-to, so the High Peaks
    3,500 ft limit applies wherever the land is the High Peaks Wilderness."""
    stand_in = SimpleNamespace(geom=point, site_type="")
    limits = elevation_limits(stand_in, land_names)
    feet = elevation_m * FT_PER_M
    if not limits:
        return True, f"About {feet:,.0f} ft; no DEC elevation limit applies here."
    for _rule, limit in limits:
        if feet > limit - ELEVATION_MARGIN_FT:
            return False, (
                f"About {feet:,.0f} ft, too close to or above the {limit:,.0f} ft limit."
            )
    tightest = min(limit for _, limit in limits)
    return True, f"About {feet:,.0f} ft, below the {tightest:,.0f} ft DEC limit."


# --- 3-4. scoring and spread ---------------------------------------------------------------


def spread(candidates: list[dict], min_spacing_m: float, max_results: int) -> list[dict]:
    """Highest score first; each kept one at least `min_spacing_m` along the trail from
    every other kept one; at most `max_results`; returned in order along the trail."""
    ranked = sorted(candidates, key=lambda c: (-(c["score"] or 0), c["distance_along_m"], c["id"]))
    kept: list[dict] = []
    for candidate in ranked:
        if len(kept) >= max_results:
            break
        if all(
            abs(candidate["distance_along_m"] - other["distance_along_m"]) >= min_spacing_m
            for other in kept
        ):
            kept.append(candidate)
    return sorted(kept, key=lambda c: c["distance_along_m"])


def candidate_id(point: Point) -> str:
    """Stable and self-describing: a plan can store it and find the point again."""
    return f"candidate/{point.x:.6f},{point.y:.6f}"


def empty_reason(counts: dict, within_m: float, settings: dict) -> str:
    """Why nothing passed: the filter that removed the last points standing."""
    within = f"{within_m:.0f} m" if within_m < 1000 else f"{within_m / 1000:g} km"
    if counts["sampled"] == 0:
        return "The trail is too short to sample."
    last = next((key for key in reversed(FILTERS) if counts["rejected"][key]), "public_land")
    return {
        "public_land": f"No public land with open access within {within} of this trail.",
        "trail": f"No open public land at least 150 ft from every trail within {within}.",
        "water": (f"No open public land at least 150 ft from trails and water within {within}."),
        "terrain": "Elevation data is unavailable right now, so slope could not be checked.",
        "elevation": f"No open public land below the DEC elevation limits within {within}.",
        "slope": (
            f"No public land with gentle slope (≤ {settings['max_slope_deg']}°) within "
            f"{within} of this trail."
        ),
    }[last]


def find_candidates(route_geom: GEOSGeometry, within_m: float, settings: dict) -> dict:
    """The whole search for one route and corridor: candidates, counts and timing."""
    started = time.perf_counter()
    line_m, _ = stitch(route_geom)
    samples = sample_points(line_m, within_m, settings)
    rule = float(settings["rule_distance_m"])
    counts = {"sampled": len(samples), "rejected": dict.fromkeys(FILTERS, 0)}
    alive = list(range(len(samples)))

    land = public_land(samples, alive) if alive else {}
    passed = [i for i in alive if land.get(i, {}).get("access") == "open"]
    counts["rejected"]["public_land"] = len(alive) - len(passed)
    alive = passed

    for key, table in (("trail", "geodata_trail"), ("water", "geodata_waterfeature")):
        too_close = near(table, samples, alive, rule) if alive else set()
        counts["rejected"][key] = len(too_close)
        alive = [i for i in alive if i not in too_close]

    points = to_wgs84(samples, alive)
    # Elevation first, one 3DEP sample per point: the DEC limits remove most points on a
    # High Peaks trail, and each costs one sample here against nine for its slope.
    heights: dict[int, float] = {}
    if alive:
        try:
            values, _ = elevation.fetch_elevations([points[i] for i in alive])
        except AnalysisError:
            values = [None] * len(alive)
        heights = {i: v for i, v in zip(alive, values, strict=True) if v is not None}
    unavailable = len(alive) - len(heights)
    alive = [i for i in alive if i in heights]

    elevation_notes = {}
    passed = []
    for i in alive:
        ok, note = elevation_check(points[i], heights[i], land[i]["names"])
        if ok:
            passed.append(i)
            elevation_notes[i] = note
    counts["rejected"]["elevation"] = len(alive) - len(passed)
    alive = passed

    terrain = {}
    if alive:
        outcomes = SiteTerrain().run_many(
            [points[i] for i in alive], {"stencil_m": settings["stencil_m"]}
        )
        terrain = {
            i: outcome.value
            for i, outcome in zip(alive, outcomes, strict=True)
            if not isinstance(outcome, AnalysisError)
        }
    counts["rejected"]["terrain"] = unavailable + len(alive) - len(terrain)
    alive = [i for i in alive if i in terrain]

    max_slope = float(settings["max_slope_deg"])
    passed = [i for i in alive if terrain[i]["slope_deg"] <= max_slope]
    counts["rejected"]["slope"] = len(alive) - len(passed)
    alive = passed
    counts["passed"] = len(alive)

    # Scoring is the costly step (about 0.1 s a point), so only the flattest survivor at
    # each station is scored, and at most `max_scored` of those, evenly along the trail.
    # The spread keeps one per ~0.5 mi anyway, so this loses nothing a hiker would see.
    best_at: dict[float, int] = {}
    for i in alive:
        station = samples[i]["station_along_m"]
        if (
            station not in best_at
            or terrain[i]["slope_deg"] < terrain[best_at[station]]["slope_deg"]
        ):
            best_at[station] = i
    alive = [best_at[station] for station in sorted(best_at)]
    limit = int(settings["max_scored"])
    if len(alive) > limit:
        step = len(alive) / limit
        alive = [alive[int(k * step)] for k in range(limit)]
    counts["scored"] = len(alive)

    scoring = load_scoring_config()
    # Tonight's forecast does not belong in an answer cached for weeks.
    scoring = replace(scoring, weights={k: v for k, v in scoring.weights.items() if k != "weather"})
    scored = []
    for i in alive:
        point = points[i]
        result = score_location(point.x, point.y, scoring, stored_only=True)
        sample = samples[i]
        scored.append(
            {
                "index": i,
                "id": candidate_id(point),
                "lon": round(point.x, 6),
                "lat": round(point.y, 6),
                "distance_along_m": round(line_m.project(Point(sample["x"], sample["y"])), 1),
                "distance_from_route_m": round(
                    line_m.distance(Point(sample["x"], sample["y"], srid=METRIC_SRID)), 1
                ),
                "side": sample["side"],
                "score": result["score"],
                "suitability_score": result.get("suitability_score"),
                "score_breakdown": result,
            }
        )
    kept = spread(scored, float(settings["min_spacing_m"]), int(settings["max_results"]))
    counts["kept"] = len(kept)

    candidates = []
    for candidate in kept:
        i = candidate.pop("index")
        sample = samples[i]
        trail_m = nearest_m("geodata_trail", sample["x"], sample["y"])
        water_m = nearest_m("geodata_waterfeature", sample["x"], sample["y"])
        where = land[i]["display"]
        slope = terrain[i]["slope_deg"]
        candidates.append(
            {
                **candidate,
                "kind": "candidate",
                "label": LABEL,
                "confidence": computed_payload(),
                "checks": [
                    {
                        "key": "public_land",
                        "passed": True,
                        "label": f"On public land with open access ({where}).",
                    },
                    {
                        "key": "trail",
                        "passed": True,
                        "label": (
                            f"At least 150 ft from any mapped trail (nearest {trail_m:.0f} m)."
                            if trail_m is not None
                            else "At least 150 ft from any mapped trail."
                        ),
                    },
                    {
                        "key": "water",
                        "passed": True,
                        "label": f"At least 150 ft from mapped water (nearest {water_m:.0f} m)."
                        if water_m is not None
                        else "No mapped water nearby.",
                    },
                    {"key": "elevation", "passed": True, "label": elevation_notes[i]},
                    {
                        "key": "slope",
                        "passed": True,
                        "label": f"Gentle ground: {slope:.1f}° (limit {max_slope:g}°).",
                    },
                ],
                "not_checked": ROAD_NOTE,
                "rule": RULES["designated_150"],
                "elevation_m": round(terrain[i]["elevation_m"], 1),
                "slope_deg": round(slope, 1),
                "nearest_trail_m": trail_m,
                "nearest_water_m": water_m,
            }
        )
    return {
        "candidates": candidates,
        "counts": counts,
        "reason": None if candidates else empty_reason(counts, within_m, settings),
        "line_length_m": round(line_m.length, 1),
        "compute_ms": round((time.perf_counter() - started) * 1000),
    }


class TrailCandidates(Analysis):
    """The search as an analysis, so each answer is cached with provenance: keyed by the
    route geometry, the corridor and the config. Land, trails and water change only when
    re-ingested, so answers keep for 30 days."""

    name = "trail_candidates"
    version = "1"
    ttl = timedelta(days=30)
    grid_degrees = None

    def canonical_params(self, params: dict) -> dict:
        return {
            "within_m": int(params.get("within_m", 500)),
            "config": config_digest(config()),
            "scoring": load_scoring_config().digest,
        }

    def compute(self, geom, window, params) -> Computed:
        value = find_candidates(geom, params["within_m"], config())
        provenance = {
            "sources": ["padus", "osm-trails", "nhd", "usgs-3dep"],
            "sampled": value["counts"]["sampled"],
            "kept": value["counts"]["kept"],
        }
        return Computed(value, provenance)
