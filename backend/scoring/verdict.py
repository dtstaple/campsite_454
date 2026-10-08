"""
The legality verdict a user sees for a campsite (TM05-76 follow-up): "Permitted ·
designated site", "Not permitted", or "Unknown: check current rules".

`legal_status` (legal_gate.py) answers "is camping allowed on this land?" from PAD-US.
The verdict adds what is known about the *site*: whether it is a designated campsite, and
the elevation limits NYS DEC sets for the Adirondacks. docs/scoring.md has the rules and
their sources.

Rules, from official NYS DEC pages (fetched 2026-10-07):

  ADIRONDACK_4000  "Except in an emergency, camping is prohibited above an elevation of
                   4,000 feet in the Adirondacks." (State Land Camping Rules)
  HIGH_PEAKS_3500  "No camping above 3,500 feet (except at lean-to)" (High Peaks Wilderness
                   Complex)
  DESIGNATED_150   "Camping is prohibited within 150 feet of any road, trail, spring,
                   stream, pond or other body of water except at areas designated by a
                   'Camp Here' disk." (State Land Camping Rules)

The verdict never claims more than the data supports:

- **Designated**, and clear of every elevation limit by ELEVATION_MARGIN_FT: Permitted.
  A designated site within the margin of a limit, or above it, is Unknown. 3DEP's
  elevation at a point is not exact, and our designation evidence is not DEC's own list.
  Sno-bird (4,028 ft, tagged "NYSDEC designated campsite") is the case.
- **Designation not confirmed:** Not permitted only where a verified rule is clearly
  broken (above a limit by more than the margin). Otherwise Unknown: at-large camping
  also needs 150 ft from roads, which the database does not have.
- Land marked **closed** is Not permitted; a "designated" site on closed land is Unknown
  (the data disagree).
"""

from __future__ import annotations

from geodata.models import Campsite

PERMITTED, NOT_PERMITTED, UNKNOWN = "permitted", "not_permitted", "unknown"

FT_PER_M = 3.28084
#: Elevations within this many feet of a limit are not decided either way.
ELEVATION_MARGIN_FT = 50

#: The Adirondack Park, roughly the Blue Line (backend/pipeline/regions.yml).
ADIRONDACK_BBOX = (-75.40, 43.00, -73.30, 44.90)

STATE_LAND_RULES_URL = "https://dec.ny.gov/things-to-do/camping/state-land-rules"
HIGH_PEAKS_URL = "https://dec.ny.gov/places/high-peaks-wilderness-complex"

RULES = {
    "adirondack_4000": {
        "text": "Except in an emergency, camping is prohibited above an elevation of "
        "4,000 feet in the Adirondacks.",
        "source": STATE_LAND_RULES_URL,
    },
    "high_peaks_3500": {
        "text": "No camping above 3,500 feet (except at lean-to).",
        "source": HIGH_PEAKS_URL,
    },
    "designated_150": {
        "text": "Camping is prohibited within 150 feet of any road, trail, spring, stream, "
        "pond or other body of water except at areas designated by a 'Camp Here' disk.",
        "source": STATE_LAND_RULES_URL,
    },
}

LABELS = {
    PERMITTED: "Permitted · designated site",
    NOT_PERMITTED: "Not permitted",
    UNKNOWN: "Unknown: check current rules",
}


def designation(site: Campsite) -> str | None:
    """Why we believe the site is a designated campsite, or None if we cannot say."""
    if site.source == Campsite.Source.RIDB:
        return "listed by Recreation.gov"
    if site.site_type == Campsite.SiteType.LEAN_TO:
        return "a lean-to"
    tags = (site.raw or {}).get("tags") or {}
    text = " ".join(str(tags.get(key, "")) for key in ("description", "designation", "note"))
    if "designated" in text.lower():
        return "described as a designated campsite in OpenStreetMap"
    operator = str(tags.get("operator", "")).replace(" ", "").upper()
    if "DEC" in operator:
        return "mapped as operated by NYSDEC in OpenStreetMap"
    return None


def in_adirondacks(site: Campsite) -> bool:
    west, south, east, north = ADIRONDACK_BBOX
    return west <= site.geom.x <= east and south <= site.geom.y <= north


def elevation_limits(site: Campsite, land_name: str | None) -> list[tuple[str, float]]:
    """The (rule key, limit in feet) pairs that apply where the site is."""
    if not in_adirondacks(site):
        return []
    limits = [("adirondack_4000", 4000.0)]
    is_lean_to = site.site_type == Campsite.SiteType.LEAN_TO
    if land_name and "high peaks wilderness" in land_name.lower() and not is_lean_to:
        limits.append(("high_peaks_3500", 3500.0))
    return limits


def legality_verdict(site: Campsite, facts=None, legal_status: dict | None = None) -> dict:
    """The verdict for one campsite. `facts` is its CampsiteFacts (or None); `legal_status`
    the score's land-based gate (or None when the site is not scored)."""
    designated = designation(site)
    elevation_ft = (
        round(facts.elevation_m * FT_PER_M)
        if facts is not None and facts.elevation_m is not None
        else None
    )
    land = (legal_status or {}).get("status")
    land_name = getattr(facts, "land_name", None) or None

    def verdict(status: str, reason: str, rule: str | None = None) -> dict:
        return {
            "verdict": status,
            "label": LABELS[status],
            "reason": reason,
            "rule": RULES.get(rule) if rule else None,
            "designated": designated is not None,
            "designation_basis": designated,
            "elevation_ft": elevation_ft,
        }

    if land == "not_permitted":
        if designated:
            return verdict(
                UNKNOWN,
                f"Recorded as a designated site ({designated}), but the land is marked "
                "closed to the public. Check before you go.",
            )
        return verdict(NOT_PERMITTED, (legal_status or {}).get("reason", "Land closed."))

    limits = elevation_limits(site, land_name)
    for rule, limit in limits:
        if elevation_ft is None:
            break
        if elevation_ft > limit + ELEVATION_MARGIN_FT and not designated:
            return verdict(
                NOT_PERMITTED,
                f"At about {elevation_ft:,} ft, above the {limit:,.0f} ft camping limit.",
                rule,
            )
        if elevation_ft >= limit - ELEVATION_MARGIN_FT:
            what = f"Recorded as a designated site ({designated}), but at" if designated else "At"
            return verdict(
                UNKNOWN,
                f"{what} about {elevation_ft:,} ft, too close to the {limit:,.0f} ft camping "
                "limit to call from the elevation data.",
                rule,
            )

    if designated:
        if limits and elevation_ft is None:
            return verdict(
                UNKNOWN,
                f"Recorded as a designated site ({designated}), but its elevation is not "
                "known, so the elevation limits cannot be checked.",
            )
        return verdict(PERMITTED, f"Designated campsite: {designated}.")
    return verdict(
        UNKNOWN,
        "Not a designated site we can confirm. At-large camping is allowed on open "
        "Forest Preserve land at least 150 ft from roads, trails and water, which cannot "
        "all be checked here.",
        "designated_150",
    )


#: Appended to the trail factor's explanation for a designated site that is close to a
#: trail: the 150 ft rule does not apply to designated sites, and many sit by the trail.
DESIGNATED_NEAR_TRAIL_NOTE = (
    " Designated sites are often this close to a trail; that is normal for a designated site."
)
