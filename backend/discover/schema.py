"""
The strict schema of a trip request (TM05-170): what CampSite can search on, and nothing
else. docs/api.md, "Natural-language trip finder", lists every field.

Both the language model and the keyword parser produce this shape, and `validate()` checks
it the same way for both. Anything outside it is rejected, not repaired: an unknown key, a
wrong type, a number out of range, a region that isn't in pipeline/regions.yml, or a
minimum above its maximum. The Messages API's structured outputs can't express numeric
ranges or string lengths (docs: "JSON Schema Limitations"), so `json_schema()` gives the
model the shape and `validate()` enforces the rest.
"""

from __future__ import annotations

import math
from functools import cache

from accounts.weights import defaults as default_weights
from pipeline.regions import load_regions

#: Bumped whenever the schema changes, so cached interpretations are not reused.
VERSION = "1"

DIFFICULTIES = ("easy", "moderate", "hard")
ROUTE_TYPES = ("loop", "out_and_back", "point_to_point")

MAX_LENGTH_MI = 300.0
MAX_GAIN_FT = 30_000.0
MAX_NIGHTS = 30
MAX_UNSUPPORTED = 5
MAX_UNSUPPORTED_CHARS = 60


class SchemaError(ValueError):
    """Output that doesn't match the schema. The message says which rule it broke."""


@cache
def regions() -> dict[str, str]:
    """Region id -> label, from pipeline/regions.yml."""
    return {rid: getattr(aoi, "label", rid) or rid for rid, aoi in load_regions().items()}


@cache
def factors() -> tuple[str, ...]:
    """The scoring factors a weight can name, in config order."""
    return tuple(default_weights())


def fields() -> tuple[str, ...]:
    return (
        "min_length_mi",
        "max_length_mi",
        "min_gain_ft",
        "max_gain_ft",
        "difficulty",
        "route_type",
        "nights",
        "has_campsites",
        "water_view",
        "sheltered",
        "region",
        "weights",
        "unsupported",
    )


def empty() -> dict:
    """A request that asks for nothing."""
    return {
        **{name: None for name in fields()},
        "difficulty": [],
        "route_type": [],
        "unsupported": [],
    }


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def json_schema() -> dict:
    """The shape for the Messages API's structured outputs (output_config.format)."""
    weights = {
        "type": "object",
        "properties": {name: _nullable({"type": "number"}) for name in factors()},
        "required": list(factors()),
        "additionalProperties": False,
    }
    properties = {
        "min_length_mi": _nullable({"type": "number"}),
        "max_length_mi": _nullable({"type": "number"}),
        "min_gain_ft": _nullable({"type": "number"}),
        "max_gain_ft": _nullable({"type": "number"}),
        "difficulty": {"type": "array", "items": {"type": "string", "enum": list(DIFFICULTIES)}},
        "route_type": {"type": "array", "items": {"type": "string", "enum": list(ROUTE_TYPES)}},
        "nights": _nullable({"type": "integer"}),
        "has_campsites": _nullable({"type": "boolean"}),
        "water_view": _nullable({"type": "boolean"}),
        "sheltered": _nullable({"type": "boolean"}),
        "region": _nullable({"type": "string", "enum": list(regions())}),
        "weights": _nullable(weights),
        "unsupported": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(fields()),
        "additionalProperties": False,
    }


def _number(name: str, value, maximum: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SchemaError(f"{name} must be a number or null")
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise SchemaError(f"{name} must be between 0 and {maximum:g}")
    return float(value)


def _flag(name: str, value) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise SchemaError(f"{name} must be true, false or null")
    return value


def _choices(name: str, value, allowed: tuple[str, ...]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SchemaError(f"{name} must be a list of strings")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise SchemaError(f"{name} has unknown values: {', '.join(unknown)}")
    if len(set(value)) != len(value):
        raise SchemaError(f"{name} repeats a value")
    return [v for v in allowed if v in value]  # canonical order


def _weights(value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != set(factors()):
        raise SchemaError(f"weights must be null or an object with exactly: {', '.join(factors())}")
    weights = {name: _number(f"weights.{name}", value[name], 1.0) for name in factors()}
    if all(w is None for w in weights.values()):
        return None
    return weights


def _unsupported(value) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SchemaError("unsupported must be a list of strings")
    if len(value) > MAX_UNSUPPORTED:
        raise SchemaError(f"unsupported has more than {MAX_UNSUPPORTED} items")
    cleaned = []
    for item in value:
        text = " ".join(item.split())
        if not text or len(text) > MAX_UNSUPPORTED_CHARS:
            raise SchemaError(f"each unsupported item must be 1-{MAX_UNSUPPORTED_CHARS} characters")
        if any(not ch.isprintable() for ch in text) or "<" in text or ">" in text:
            raise SchemaError("unsupported items must be plain text")
        if text.lower() not in (c.lower() for c in cleaned):
            cleaned.append(text)
    return cleaned


def validate(raw) -> dict:
    """The request, checked and normalised. SchemaError for anything outside the schema."""
    if not isinstance(raw, dict):
        raise SchemaError("the interpretation must be a JSON object")
    keys = set(raw)
    if keys != set(fields()):
        extra, missing = sorted(keys - set(fields())), sorted(set(fields()) - keys)
        parts = []
        if extra:
            parts.append(f"unknown keys: {', '.join(extra)}")
        if missing:
            parts.append(f"missing keys: {', '.join(missing)}")
        raise SchemaError("; ".join(parts))

    out = {
        "min_length_mi": _number("min_length_mi", raw["min_length_mi"], MAX_LENGTH_MI),
        "max_length_mi": _number("max_length_mi", raw["max_length_mi"], MAX_LENGTH_MI),
        "min_gain_ft": _number("min_gain_ft", raw["min_gain_ft"], MAX_GAIN_FT),
        "max_gain_ft": _number("max_gain_ft", raw["max_gain_ft"], MAX_GAIN_FT),
        "difficulty": _choices("difficulty", raw["difficulty"], DIFFICULTIES),
        "route_type": _choices("route_type", raw["route_type"], ROUTE_TYPES),
        "nights": raw["nights"],
        "has_campsites": _flag("has_campsites", raw["has_campsites"]),
        "water_view": _flag("water_view", raw["water_view"]),
        "sheltered": _flag("sheltered", raw["sheltered"]),
        "region": raw["region"],
        "weights": _weights(raw["weights"]),
        "unsupported": _unsupported(raw["unsupported"]),
    }
    nights = out["nights"]
    if nights is not None and (
        isinstance(nights, bool) or not isinstance(nights, int) or not 0 <= nights <= MAX_NIGHTS
    ):
        raise SchemaError(f"nights must be a whole number from 0 to {MAX_NIGHTS}, or null")
    if out["region"] is not None and out["region"] not in regions():
        raise SchemaError(f"region must be one of {', '.join(regions())}, or null")
    for low, high in (("min_length_mi", "max_length_mi"), ("min_gain_ft", "max_gain_ft")):
        if out[low] is not None and out[high] is not None and out[low] > out[high]:
            raise SchemaError(f"{low} is above {high}")
    if out["max_length_mi"] == 0:
        raise SchemaError("max_length_mi must be above 0")
    return out


def is_empty(interpretation: dict) -> bool:
    """True when the request asks for nothing CampSite can search or show."""
    return all(interpretation[name] in (None, [], {}) for name in fields() if name != "unsupported")
