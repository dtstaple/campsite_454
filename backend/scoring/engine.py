"""
The scoring engine: evaluate every configured factor at a location and combine them into
the contract-1 result described in docs/scoring.md.

    from scoring.engine import score_location
    result = score_location(-73.95, 44.18)
    result["score"]          # 0-100
    result["factors"]        # the per-factor breakdown

The combination is a weighted mean over the factors that could be evaluated:

    total = sum(weight_i * score_i) / sum(weight_i)     for status != not_available

then any caps (land marked closed) are applied. Each factor's `contribution` is its share
of that total, so the breakdown always adds up to the number shown.

Alongside it (TM05-76): `legal_status`, the legal gate (scoring/legal_gate.py), and
`suitability_score`, the same weighted mean without the legal factor -- how good a place
it is to camp, separate from whether you may.
"""

from __future__ import annotations

from scoring.config import ScoringConfig, ScoringConfigError, load
from scoring.factors import FACTORS, NOT_AVAILABLE, FactorResult
from scoring.legal_gate import legal_status

CONTRACT_VERSION = 1


class ScoringError(Exception):
    """A location could not be scored."""


def build_factors(config: ScoringConfig, stored_only: bool = False):
    unknown = [key for key in config.weights if key not in FACTORS]
    if unknown:
        raise ScoringConfigError(f"weights name unknown factors: {', '.join(unknown)}")
    return [FACTORS[key](config.factor(key), stored_only) for key in config.weights]


def score_location(
    lon: float, lat: float, config: ScoringConfig | None = None, stored_only: bool = False
) -> dict:
    """Score the point (lon, lat), WGS84 degrees, from its coordinates alone.

    `stored_only` answers from stored values and makes no live call: a factor whose
    analysis (3DEP slope, Open-Meteo weather) is not already cached is not_available
    rather than fetched."""
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ScoringError(f"not a valid longitude/latitude: ({lon}, {lat})")
    config = config or load()
    results = [factor.evaluate(lon, lat) for factor in build_factors(config, stored_only)]
    return combine(results, config, lon, lat)


def score_campsite(
    campsite, config: ScoringConfig | None = None, stored_only: bool = False
) -> dict:
    """Score a Campsite by its location. Nothing about the record itself is a factor --
    capacity in particular is not (571 of 660 RIDB sites report the same 8)."""
    return score_location(campsite.geom.x, campsite.geom.y, config, stored_only)


def combine(results: list[FactorResult], config: ScoringConfig, lon: float, lat: float) -> dict:
    counted = [r for r in results if r.status != NOT_AVAILABLE]
    total_weight = sum(config.weights[r.key] for r in counted)
    if total_weight <= 0:
        raise ScoringError("no factor with a positive weight could be evaluated")

    factors, total = [], 0.0
    for r in results:
        weight = config.weights[r.key]
        effective = weight / total_weight if r.status != NOT_AVAILABLE else 0.0
        contribution = (r.score or 0.0) * effective
        total += contribution
        factors.append(
            {
                "key": r.key,
                "label": r.label,
                "status": r.status,
                "score": None if r.score is None else round(r.score, 1),
                "weight": weight,
                "effective_weight": round(effective, 4),
                "contribution": round(contribution, 1),
                "measurement": r.measurement,
                "explanation": r.explanation,
            }
        )

    caps = [cap for r in counted for cap in r.caps]
    for cap in caps:
        total = min(total, cap["max_score"])

    legal = next((r for r in results if r.key == "legal"), None)

    return {
        "contract": CONTRACT_VERSION,
        "model_version": config.model_version,
        "config_digest": config.digest,
        "location": {"lon": round(lon, 6), "lat": round(lat, 6)},
        "score": int(round(max(0.0, min(100.0, total)))),
        "factors": factors,
        "caps": caps,
        "suitability_score": suitability(counted, config),
        "legal_status": legal_status(legal, config.factor("legal").get("gate")),
    }


def suitability(counted: list[FactorResult], config: ScoringConfig) -> int | None:
    """The weighted mean over every evaluated factor except legality (TM05-76), with no
    caps: legal caps are legality, which legal_status reports. None when nothing but
    legality could be evaluated."""
    rest = [r for r in counted if r.key != "legal"]
    weight = sum(config.weights[r.key] for r in rest)
    if weight <= 0:
        return None
    total = sum(config.weights[r.key] * (r.score or 0.0) for r in rest) / weight
    return int(round(max(0.0, min(100.0, total))))
