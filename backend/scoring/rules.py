"""
Per-region camping rules (TM05-118), loaded from scoring/legality.yml.

The file says, for each region, where it is, which authority's rules apply, what counts
as evidence of a designated site there, and the rules themselves, each quoted from an
official source. This module only reads and checks that file; verdict.py applies it.

A rule has one of a fixed set of kinds, so a new region needs no new code:

    max_elevation   no camping above `limit` (optionally only on matching land, and not
                    at exempt site types)
    no_camping      no camping on matching land
    setback         no camping within `distance` of a trail or water (matching names or
                    land), except at designated sites
    undesignated    the rule cited, with `reason`, when a site's designation cannot be
                    confirmed; exactly one per region that has rules

Units travel with every number (`{value: 200, unit: ft}`), so a region in metres is as
easy to write as one in feet.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path

import yaml

LEGALITY_PATH = Path(__file__).with_name("legality.yml")

KINDS = ("max_elevation", "no_camping", "setback", "undesignated")
WHERE_KEYS = ("land_name_contains", "land_name_in", "trail_name_in", "water_name_in")
FROM = ("trail", "water")
M_PER_UNIT = {"m": 1.0, "km": 1000.0, "ft": 0.3048, "mi": 1609.344}


class LegalityConfigError(ValueError):
    """legality.yml is malformed. Raised at load, never at request time."""


@dataclass(frozen=True)
class Length:
    value: float
    unit: str

    @property
    def metres(self) -> float:
        return self.to("m")

    def feet(self) -> float:
        return self.to("ft")

    def to(self, unit: str) -> float:
        """In `unit`, exactly when it is already in that unit: a 4,000 ft limit stays
        4000.0, not 3999.9999999999995 after a round trip through metres."""
        if unit == self.unit:
            return self.value
        return self.value * M_PER_UNIT[self.unit] / M_PER_UNIT[unit]

    def label(self) -> str:
        return f"{self.value:,g} {self.unit}"


def format_length(metres: float, unit: str) -> str:
    """A measured distance in a rule's unit: whole feet or metres, two decimals of miles or
    kilometres."""
    value = metres / M_PER_UNIT[unit]
    return f"{value:,.0f} {unit}" if unit in ("ft", "m") else f"{value:,.2f} {unit}"


@dataclass(frozen=True)
class Rule:
    id: str
    kind: str
    text: str
    source_url: str
    limit: Length | None = None
    distance: Length | None = None
    origin: str | None = None  # `from`: trail or water
    where: dict = field(default_factory=dict)
    exempt: tuple[str, ...] = ()
    reason: str | None = None

    def cited(self) -> dict:
        """The rule as a verdict cites it."""
        return {"text": self.text, "source": self.source_url}

    def applies_on(self, land_name: str | None, trail_name=None, water_name=None) -> bool:
        """Whether the rule's `where` matches. No `where` means everywhere in the region."""
        if not self.where:
            return True
        land = (land_name or "").lower()
        for key, values in self.where.items():
            wanted = [v.lower() for v in values]
            if key == "land_name_contains" and any(v in land for v in wanted):
                return True
            if key == "land_name_in" and land in wanted:
                return True
            if key == "trail_name_in" and (trail_name or "").lower() in wanted:
                return True
            if key == "water_name_in" and (water_name or "").lower() in wanted:
                return True
        return False


@dataclass(frozen=True)
class Operator:
    match: str
    basis: str


@dataclass(frozen=True)
class Region:
    key: str
    label: str
    authority: str
    authority_short: str
    bbox: tuple[float, float, float, float]
    operators: tuple[Operator, ...]
    rules: tuple[Rule, ...]
    unchecked: tuple[dict, ...]

    def contains(self, lon: float, lat: float) -> bool:
        west, south, east, north = self.bbox
        return west <= lon <= east and south <= lat <= north

    def of_kind(self, kind: str) -> list[Rule]:
        return [rule for rule in self.rules if rule.kind == kind]

    @property
    def undesignated(self) -> Rule | None:
        found = self.of_kind("undesignated")
        return found[0] if found else None


@dataclass(frozen=True)
class Legality:
    elevation_margin: Length
    distance_margin: Length
    regions: tuple[Region, ...]

    def region_at(self, lon: float, lat: float) -> Region | None:
        """The first region (in file order) whose area contains the point."""
        return next((r for r in self.regions if r.contains(lon, lat)), None)


def _length(raw, where: str) -> Length:
    if not isinstance(raw, dict) or set(raw) != {"value", "unit"}:
        raise LegalityConfigError(f"{where}: expected {{value, unit}}, got {raw!r}")
    if raw["unit"] not in M_PER_UNIT:
        raise LegalityConfigError(f"{where}: unknown unit {raw['unit']!r}")
    return Length(float(raw["value"]), raw["unit"])


def _rule(raw: dict, sources: dict, where: str) -> Rule:
    kind = raw.get("kind")
    if kind not in KINDS:
        raise LegalityConfigError(f"{where}: unknown rule kind {kind!r}")
    for key in ("id", "text", "source"):
        if not raw.get(key):
            raise LegalityConfigError(f"{where}: rule needs `{key}`")
    if raw["source"] not in sources:
        raise LegalityConfigError(f"{where}: unknown source {raw['source']!r}")
    match = raw.get("where") or {}
    unknown = set(match) - set(WHERE_KEYS)
    if unknown:
        raise LegalityConfigError(f"{where}: unknown `where` keys {sorted(unknown)}")
    rule = Rule(
        id=raw["id"],
        kind=kind,
        text=raw["text"],
        source_url=sources[raw["source"]]["url"],
        where={key: list(values) for key, values in match.items()},
        exempt=tuple(raw.get("exempt") or ()),
        reason=raw.get("reason"),
    )
    if kind == "max_elevation":
        return replace(rule, limit=_length(raw.get("limit"), f"{where}.limit"))
    if kind == "setback":
        if raw.get("from") not in FROM:
            raise LegalityConfigError(f"{where}: setback `from` must be one of {FROM}")
        return replace(
            rule, distance=_length(raw.get("distance"), f"{where}.distance"), origin=raw["from"]
        )
    if kind == "no_camping" and not match:
        raise LegalityConfigError(f"{where}: no_camping needs a `where`")
    if kind == "undesignated" and not raw.get("reason"):
        raise LegalityConfigError(f"{where}: undesignated needs a `reason`")
    return rule


def _region(key: str, raw: dict) -> Region:
    sources = raw.get("sources") or {}
    for name, source in sources.items():
        if not (source or {}).get("url"):
            raise LegalityConfigError(f"{key}.sources.{name}: needs a `url`")
    bbox = (raw.get("area") or {}).get("bbox")
    if not bbox or len(bbox) != 4:
        raise LegalityConfigError(f"{key}: area needs a bbox [west, south, east, north]")
    rules = tuple(
        _rule(rule, sources, f"{key}.rules[{i}]") for i, rule in enumerate(raw.get("rules") or [])
    )
    ids = [rule.id for rule in rules]
    if len(ids) != len(set(ids)):
        raise LegalityConfigError(f"{key}: rule ids must be unique")
    if rules and sum(rule.kind == "undesignated" for rule in rules) != 1:
        raise LegalityConfigError(f"{key}: a region with rules needs exactly one `undesignated`")
    unchecked = tuple(raw.get("unchecked") or ())
    for item in unchecked:
        if not item.get("text") or item.get("source") not in sources:
            raise LegalityConfigError(f"{key}.unchecked: each needs `text` and a known `source`")
    authority = raw.get("authority") or {}
    operators = (raw.get("designation") or {}).get("operators", [])
    return Region(
        key=key,
        label=raw.get("label") or key,
        authority=authority.get("name", ""),
        authority_short=authority.get("short", ""),
        bbox=tuple(float(v) for v in bbox),
        operators=tuple(Operator(o["match"], o["basis"]) for o in operators),
        rules=rules,
        unchecked=unchecked,
    )


def parse(raw: dict) -> Legality:
    if (raw or {}).get("version") != 1:
        raise LegalityConfigError("legality.yml: `version: 1` expected")
    margins = raw.get("margins") or {}
    return Legality(
        elevation_margin=_length(margins.get("elevation"), "margins.elevation"),
        distance_margin=_length(margins.get("distance"), "margins.distance"),
        regions=tuple(_region(key, value) for key, value in (raw.get("regions") or {}).items()),
    )


@cache
def legality() -> Legality:
    """The rules in effect, read once per process."""
    return parse(yaml.safe_load(LEGALITY_PATH.read_text()))
