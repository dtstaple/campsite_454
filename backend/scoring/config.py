"""
Loads and validates scoring/config.yml.

Weights and curve parameters live in config so they can be tuned without a code change
(TM05-43 AC). The digest identifies the exact configuration a score came from, so a
cached score can be recognised as stale after any edit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yml"


class ScoringConfigError(Exception):
    """The scoring config is missing, unreadable, or inconsistent."""


@dataclass(frozen=True)
class ScoringConfig:
    model_version: str
    weights: dict[str, float]
    factors: dict[str, dict]
    digest: str

    def factor(self, key: str) -> dict:
        return self.factors.get(key) or {}


def _digest(raw: dict) -> str:
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]


def parse(raw: object, source: str = "<config>") -> ScoringConfig:
    if not isinstance(raw, dict):
        raise ScoringConfigError(f"{source}: expected a mapping at the top level")
    version = raw.get("model_version")
    weights = raw.get("weights")
    factors = raw.get("factors") or {}
    if not isinstance(version, str) or not version:
        raise ScoringConfigError(f"{source}: model_version must be a non-empty string")
    if not isinstance(weights, dict) or not weights:
        raise ScoringConfigError(f"{source}: weights must be a non-empty mapping")
    for key, weight in weights.items():
        if not isinstance(weight, int | float) or isinstance(weight, bool) or weight < 0:
            raise ScoringConfigError(f"{source}: weight for {key!r} must be a number >= 0")
    if not isinstance(factors, dict):
        raise ScoringConfigError(f"{source}: factors must be a mapping")
    return ScoringConfig(
        model_version=version,
        weights={key: float(value) for key, value in weights.items()},
        factors=factors,
        digest=_digest(raw),
    )


@cache
def load(path: Path = DEFAULT_CONFIG_PATH) -> ScoringConfig:
    try:
        raw = yaml.safe_load(Path(path).read_text())
    except OSError as error:
        raise ScoringConfigError(f"cannot read scoring config {path}: {error}") from error
    return parse(raw, str(path))
