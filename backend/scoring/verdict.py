"""
The legality verdict a user sees for a campsite (TM05-76 follow-up): "Permitted ·
designated site", "Not permitted", or "Unknown: check current rules".

`legal_status` (legal_gate.py) answers "is camping allowed on this land?" from PAD-US.
The verdict adds what is known about the *site*: whether it is a designated campsite, and
the rules of the region it is in. Since TM05-118 those rules live in scoring/legality.yml,
one entry per region, each rule quoted from an official source; scoring/rules.py loads
them and docs/scoring.md lists them.

The verdict never claims more than the data supports:

- **Outside every region, or in one with no rules:** always Unknown, never Permitted.
- **Designated**, and clear of every rule by its margin: Permitted. A designated site
  within the margin of an elevation limit, or above it, is Unknown. 3DEP's elevation at a
  point is not exact, and our designation evidence is not the authority's own list.
  Sno-bird (4,028 ft, tagged "NYSDEC designated campsite") is the case.
- **Designation not confirmed:** Not permitted only where a verified rule is clearly
  broken (above an elevation limit by more than the margin, or on land closed to camping).
  Otherwise Unknown, citing the region's rule for undesignated sites, or the setback the
  site sits inside: setbacks hold "except at designated sites", and we cannot rule that out.
- Land marked **closed** is Not permitted; a "designated" site on closed land is Unknown
  (the data disagree).
"""

from __future__ import annotations

from geodata.models import Campsite
from scoring.rules import Region, Rule, format_length, legality

PERMITTED, NOT_PERMITTED, UNKNOWN = "permitted", "not_permitted", "unknown"

FT_PER_M = 3.28084
#: Elevations within this many feet of a limit are not decided either way.
ELEVATION_MARGIN_FT = legality().elevation_margin.feet()

LABELS = {
    PERMITTED: "Permitted · designated site",
    NOT_PERMITTED: "Not permitted",
    UNKNOWN: "Unknown: check current rules",
}

NO_RULES_REASON = (
    "No camping rules are recorded for this area yet, so CampSite can't say whether "
    "camping is allowed here."
)


def region_of(site) -> Region | None:
    """The region whose rules apply where the site (or any point with .geom) is."""
    return legality().region_at(site.geom.x, site.geom.y)


def designation(site: Campsite, region: Region | None = None) -> str | None:
    """Why we believe the site is a designated campsite, or None if we cannot say. The
    first three kinds of evidence hold anywhere; operators come from the site's region."""
    if site.source == Campsite.Source.RIDB:
        return "listed by Recreation.gov"
    if site.site_type == Campsite.SiteType.LEAN_TO:
        return "a lean-to"
    tags = (site.raw or {}).get("tags") or {}
    text = " ".join(str(tags.get(key, "")) for key in ("description", "designation", "note"))
    if "designated" in text.lower():
        return "described as a designated campsite in OpenStreetMap"
    region = region or region_of(site)
    operator = str(tags.get("operator", "")).replace(" ", "").upper()
    for known in region.operators if region else ():
        if known.match.replace(" ", "").upper() in operator:
            return known.basis
    return None


def elevation_limits(site, land_name: str | None) -> list[tuple[str, float]]:
    """The (rule id, limit in feet) pairs that apply where the site is. `site` needs .geom
    and .site_type; `land_name` is the protected-area name (or names) there."""
    region = region_of(site)
    if region is None:
        return []
    return [
        (rule.id, rule.limit.feet())
        for rule in region.of_kind("max_elevation")
        if rule.applies_on(land_name) and site.site_type not in rule.exempt
    ]


def undesignated_rule(site) -> dict | None:
    """The rule cited for a site whose designation cannot be confirmed, where it is."""
    region = region_of(site)
    rule = region.undesignated if region else None
    return rule.cited() if rule else None


def authority_short(site) -> str | None:
    """The short name of the authority whose rules apply where the site is (e.g. DEC)."""
    region = region_of(site)
    return (region.authority_short or None) if region else None


def legality_verdict(site: Campsite, facts=None, legal_status: dict | None = None) -> dict:
    """The verdict for one campsite. `facts` is its CampsiteFacts (or None); `legal_status`
    the score's land-based gate (or None when the site is not scored)."""
    region = region_of(site)
    designated = designation(site, region)
    elevation_ft = (
        round(facts.elevation_m * FT_PER_M)
        if facts is not None and facts.elevation_m is not None
        else None
    )
    land = (legal_status or {}).get("status")
    land_name = getattr(facts, "land_name", None) or None

    def verdict(status: str, reason: str, rule: Rule | None = None) -> dict:
        return {
            "verdict": status,
            "label": LABELS[status],
            "reason": reason,
            "rule": rule.cited() if rule else None,
            "designated": designated is not None,
            "designation_basis": designated,
            "elevation_ft": elevation_ft,
        }

    if region is None or not region.rules:
        return verdict(UNKNOWN, _no_rules_reason(designated, land))

    if land == "not_permitted":
        if designated:
            return verdict(
                UNKNOWN,
                f"Recorded as a designated site ({designated}), but the land is marked "
                "closed to the public. Check before you go.",
            )
        return verdict(NOT_PERMITTED, (legal_status or {}).get("reason", "Land closed."))

    for rule in region.of_kind("no_camping"):
        if rule.applies_on(land_name):
            if designated:
                return verdict(
                    UNKNOWN,
                    f"Recorded as a designated site ({designated}), but {land_name} is "
                    "closed to camping except at the sites the rule names. Check before you go.",
                    rule,
                )
            return verdict(NOT_PERMITTED, f"Inside {land_name}, which is closed to camping.", rule)

    rules_by_id = {rule.id: rule for rule in region.rules}
    for rule_id, limit in elevation_limits(site, land_name):
        if elevation_ft is None:
            break
        if elevation_ft > limit + ELEVATION_MARGIN_FT and not designated:
            return verdict(
                NOT_PERMITTED,
                f"At about {elevation_ft:,} ft, above the {limit:,.0f} ft camping limit.",
                rules_by_id[rule_id],
            )
        if elevation_ft >= limit - ELEVATION_MARGIN_FT:
            what = f"Recorded as a designated site ({designated}), but at" if designated else "At"
            return verdict(
                UNKNOWN,
                f"{what} about {elevation_ft:,} ft, too close to the {limit:,.0f} ft camping "
                "limit to call from the elevation data.",
                rules_by_id[rule_id],
            )

    if designated:
        if elevation_limits(site, land_name) and elevation_ft is None:
            return verdict(
                UNKNOWN,
                f"Recorded as a designated site ({designated}), but its elevation is not "
                "known, so the elevation limits cannot be checked.",
            )
        return verdict(PERMITTED, f"Designated campsite: {designated}.")

    inside = _setback_hit(region, facts, land_name)
    if inside is not None:
        rule, reason = inside
        return verdict(UNKNOWN, reason, rule)
    return verdict(UNKNOWN, region.undesignated.reason, region.undesignated)


def _setback_hit(region: Region, facts, land_name: str | None) -> tuple[Rule, str] | None:
    """The first setback an undesignated site is inside, or within the margin of. The
    distances are the enrichment's: to the nearest named trail, and nearest named water."""
    if facts is None:
        return None
    margin_m = legality().distance_margin.metres
    for rule in region.of_kind("setback"):
        name = getattr(facts, f"{rule.origin}_name", "") or ""
        distance_m = getattr(facts, f"{rule.origin}_distance_m", None)
        names = {"trail_name": name} if rule.origin == "trail" else {"water_name": name}
        if distance_m is None or not rule.applies_on(land_name, **names):
            continue
        setback_m = rule.distance.metres
        if distance_m >= setback_m + margin_m:
            continue
        about = format_length(distance_m, rule.distance.unit)
        where = name or f"the nearest {rule.origin}"
        if distance_m < setback_m - margin_m:
            return rule, (
                f"About {about} from {where}. Camping within {rule.distance.label()} of it "
                "is allowed only at designated sites, and this isn't one we can confirm."
            )
        return rule, (
            f"About {about} from {where}, too close to the {rule.distance.label()} setback "
            "to call from the map data. Inside it, camping is allowed only at designated "
            "sites, and this isn't one we can confirm."
        )
    return None


def _no_rules_reason(designated: str | None, land: str | None) -> str:
    reason = NO_RULES_REASON
    if designated:
        reason += f" It is recorded as a designated site ({designated})."
    if land == "not_permitted":
        reason += " The public-land data marks this land closed to the public."
    return reason


#: Appended to the trail factor's explanation for a designated site that is close to a
#: trail: setbacks from trails do not apply to designated sites, and many sit by the trail.
DESIGNATED_NEAR_TRAIL_NOTE = (
    " Designated sites are often this close to a trail; that is normal for a designated site."
)
