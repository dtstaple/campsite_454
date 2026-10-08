"""
Legality as a gate, reported beside the score rather than inside it (TM05-76).

The legal factor still feeds the weighted `score` (contract 1 is unchanged), but a weighted
factor can be outvoted: a site on land closed to camping could still score 70 on water and
slope alone. So every score also carries `legal_status`, decided from the same PAD-US facts
the legal factor measured, and a `suitability_score` that leaves legality out entirely.

    permitted       the land's public access is in config `permitted` (open)
    not_permitted   the land's public access is in config `not_permitted` (closed)
    unknown         anything else: restricted access, access unknown, outside every
                    mapped parcel, or the legal factor could not be evaluated

Unknown is never shown as permitted. Outside public land is unknown rather than
not_permitted: it is probably private, but PAD-US is incomplete, so we do not claim it.
"""

from __future__ import annotations

from scoring.factors import NO_DATA, NOT_AVAILABLE, FactorResult

PERMITTED = "permitted"
NOT_PERMITTED = "not_permitted"
UNKNOWN = "unknown"

LABELS = {
    PERMITTED: "Public land open to camping",
    NOT_PERMITTED: "Not permitted",
    UNKNOWN: "Legality unknown",
}

DEFAULT_GATE = {"permitted": ["open"], "not_permitted": ["closed"]}


def legal_status(legal: FactorResult | None, gate: dict | None = None) -> dict:
    """The legal gate for one location, from the legal factor's result."""
    gate = gate or DEFAULT_GATE
    if legal is None or legal.status == NOT_AVAILABLE:
        return _status(UNKNOWN, "Legal status could not be evaluated here.", None)
    measurement = legal.measurement or {}
    if legal.status == NO_DATA:
        return _status(
            UNKNOWN,
            "Not inside any mapped public land, so probably private. Shown as unknown "
            "because the public-land data is incomplete.",
            measurement,
        )
    access = measurement.get("public_access")
    if access in gate.get("not_permitted", []):
        return _status(NOT_PERMITTED, legal.explanation, measurement)
    if access in gate.get("permitted", []):
        return _status(PERMITTED, legal.explanation, measurement)
    reason = legal.explanation
    if access == "restricted":
        reason += " Camping may need a permit or be limited to designated sites."
    return _status(UNKNOWN, reason, measurement)


def _status(status: str, reason: str, basis: dict | None) -> dict:
    return {"status": status, "label": LABELS[status], "reason": reason, "basis": basis}
