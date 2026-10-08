"""
An overnight plan worked out against its trail (TM05-81).

`build_plan(route, campsites)` places each stop on the route's stitched line, puts them in
order along it, rejects any that are not on the trail, and splits the route into days at
the stops. Each day's distance, gain and loss come from the route's stored elevation
profile (days.py). Each stop carries the legality verdict (scoring/verdict.py) and a
warning unless the verdict is "permitted".

The plan always runs in the route's own direction, from the start of its stitched line,
which is the direction its profile and the trail panel's miles use.
"""

from dataclasses import dataclass

from django.contrib.gis.geos import Point

from analysis.analyses.elevation import RouteProfile, stitch
from analysis.base import AnalysisError
from api.routes import MAX_WITHIN_M, display_name, facts_of
from geodata.models import METRIC_SRID
from geodata.route_rating import ALONG, NEAR_START, position_along
from geodata.route_rating import config as route_config
from scoring.config import load as load_scoring_config
from scoring.engine import score_campsite
from scoring.verdict import PERMITTED, RULES, UNKNOWN, legality_verdict

from .days import day_stats, smoothed_profile

#: More nights than any trail here needs; a bound on one request's work.
MAX_STOPS = 30
#: A stop must be at least this close to the route: the trail panel lists campsites up
#: to this far (its largest "within" option).
MAX_STOP_DISTANCE_M = MAX_WITHIN_M


class PlanError(ValueError):
    """A plan that cannot be made, with a message for the person making it."""


CANDIDATE_PREFIX = "candidate/"
CANDIDATE_LABEL = "Potential spot (unverified)"
CANDIDATE_WARNING = (
    "{label}: a computed spot, not a mapped campsite. It passed the public land, 150 ft, "
    "elevation and slope checks, but road distance isn't checked; verify current rules "
    "on the ground."
)


class CandidateStop:
    """A potential campsite (TM05-99) chosen as a stop. Not a database row: its id,
    "candidate/<lon>,<lat>", is its position, so a plan can keep it and find it again."""

    def __init__(self, source_id: str):
        try:
            lon, lat = (float(part) for part in source_id[len(CANDIDATE_PREFIX) :].split(","))
        except ValueError:
            raise PlanError(f"{source_id} is not a potential campsite id.") from None
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise PlanError(f"{source_id} is not a potential campsite id.")
        self.source_id = source_id
        self.geom = Point(lon, lat, srid=4326)
        self.geom_m = self.geom.transform(METRIC_SRID, clone=True)


def is_candidate(site) -> bool:
    return isinstance(site, CandidateStop)


@dataclass
class Located:
    site: object
    along_m: float
    from_line_m: float
    from_route_m: float


def _name(site) -> str:
    if is_candidate(site):
        return f"The {CANDIDATE_LABEL[0].lower()}{CANDIDATE_LABEL[1:]}"
    return display_name(site)["display_name"] or "this campsite"


def _candidate_legality() -> dict:
    return {
        "verdict": UNKNOWN,
        "label": CANDIDATE_LABEL,
        "reason": "Computed from public land, trail, water, elevation and slope data. "
        "Nobody has mapped a campsite here, and road distance isn't checked.",
        "rule": RULES["designated_150"],
        "designated": False,
        "designation_basis": None,
        "elevation_ft": None,
    }


def locate(route, line_m, sites) -> list[Located]:
    """Each site's position along the line, nearest-point, in metres. Rejects a site
    that is too far from the route or lies past either end of it."""
    settings = route_config()["along"]
    located = []
    for site in sites:
        point = site.geom_m
        along = line_m.project(point)
        from_line = line_m.distance(point)
        from_route = route.geom_m.distance(point)
        if from_route > MAX_STOP_DISTANCE_M:
            raise PlanError(
                f"{_name(site)} is {from_route / 1000:.1f} km from {route.name}; a stop must "
                f"be within {MAX_STOP_DISTANCE_M / 1000:.0f} km of the trail."
            )
        position = position_along(along, line_m.length, from_line, settings)
        if position["position"] != ALONG:
            before = position["position"] == NEAR_START
            where = "before the trail's start" if before else "past its end"
            raise PlanError(
                f"{_name(site)} is off the end of {route.name}: it lies {where}, "
                f"{from_line:.0f} m from the trail. Choose a campsite along the trail."
            )
        located.append(Located(site, along, from_line, from_route))
    return sorted(located, key=lambda stop: (stop.along_m, stop.site.source_id))


def _profile(route):
    """The route's elevation profile: the stored one if there is one, otherwise computed
    (and stored) now, as the trail panel does. (value, None) or (None, reason)."""
    profile = RouteProfile()
    try:
        outcome = profile.lookup(route.geom) or profile.run(route.geom)
    except AnalysisError as error:
        return None, str(error)
    return outcome.value, None


def build_plan(route, sites) -> dict:
    """The worked-out plan for `sites` (Campsite rows, any order) along `route`."""
    if not sites:
        raise PlanError("Choose at least one campsite as an overnight stop.")
    if len(sites) > MAX_STOPS:
        raise PlanError(f"A plan can have at most {MAX_STOPS} nights.")
    ids = [site.source_id for site in sites]
    if len(set(ids)) != len(ids):
        raise PlanError("Each campsite can be a stop only once.")

    line_m, _ = stitch(route.geom)
    stops = locate(route, line_m, sites)

    profile, reason = _profile(route)
    distances = smoothed = params = None
    if profile:
        params = profile["params"]
        distances = profile["distance_m"]
        smoothed = smoothed_profile(profile["elevation_m"], params)
    length = line_m.length
    cuts = [0.0, *(stop.along_m for stop in stops), length]
    days = day_stats(cuts, distances, smoothed, params)

    config = load_scoring_config()
    stop_payloads, warnings = [], []
    for night, stop in enumerate(stops, start=1):
        site = stop.site
        if is_candidate(site):
            result = {"score": None}
            legality = _candidate_legality()
            name = {"display_name": CANDIDATE_LABEL, "display_name_derived": False}
            warning = f"Night {night}, " + CANDIDATE_WARNING.format(label=CANDIDATE_LABEL)
            warnings.append(warning)
        else:
            result = score_campsite(site, config)
            legality = legality_verdict(site, facts_of(site), result["legal_status"])
            name = display_name(site)
            warning = None
        if warning is None and legality["verdict"] != PERMITTED:
            label = name["display_name"] or "campsite"
            warning = f"Night {night}, {label}: {legality['label']}."
            if legality.get("reason"):
                warning += f" {legality['reason']}"
            warnings.append(warning)
        stop_payloads.append(
            {
                "night": night,
                "id": site.source_id,
                "kind": "candidate" if is_candidate(site) else "campsite",
                **name,
                "lon": round(site.geom.x, 6),
                "lat": round(site.geom.y, 6),
                "distance_along_m": round(stop.along_m, 1),
                "distance_from_route_m": round(stop.from_route_m, 1),
                "score": result["score"],
                "legality": legality,
                "warning": warning,
            }
        )

    labels = ["Start", *(s["display_name"] or "Campsite" for s in stop_payloads), "End"]
    for number, day in enumerate(days, start=1):
        day["day"] = number
        day["from"] = labels[number - 1]
        day["to"] = labels[number]

    profiled = profile is not None
    return {
        "trail": {
            "osm_id": route.osm_id,
            "source_id": route.source_id,
            "name": route.name,
            "length_m": round(length, 1),
        },
        "nights": len(stop_payloads),
        "stops": stop_payloads,
        "days": days,
        "totals": {
            "distance_m": round(length, 1),
            "gain_m": round(sum(d["gain_m"] for d in days), 1) if profiled else None,
            "loss_m": round(sum(d["loss_m"] for d in days), 1) if profiled else None,
        },
        "profile": {"status": "ok" if profiled else "unavailable", "reason": reason},
        "warnings": warnings,
        "_line_m": line_m,
        "_profile": profile,
    }
