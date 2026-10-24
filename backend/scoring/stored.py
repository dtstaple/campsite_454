"""
Stored factor results (TM05-86): the part of a campsite's score that only changes when the
vector data or the factor settings do, computed once and kept with the campsite's facts.

Scoring a site from scratch costs about 40 ms, nearly all of it the water factor's three
nearest-feature searches. That is fine for one panel and far too slow for a map layer: the
563 Adirondack campsites took 17 s. So the vector-data factors (water, trail, legal, land
cover) are evaluated when the site is enriched and stored, and a score is then a combine
over those plus the two factors that read the analysis cache.

Slope and weather are never stored here. Their answers already live in the analysis cache,
with its own TTL and provenance -- weather expires within the hour -- and a second copy would
outlive it. A request reads them stored-only, so it still never calls 3DEP or Open-Meteo.
Nor are the terrain factors (TM05-143): they read the site's TerrainFacts when it is
scored, because `make terrain` runs after enrichment.

Weights are not part of what is stored, so a different weighting (TM05-46) re-combines the
same results instead of invalidating them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from scoring.config import ScoringConfig, load
from scoring.engine import build_factors
from scoring.factors import FactorResult

#: Factors answered from the analysis cache on every request, never stored.
ANALYSIS_CACHE_FACTORS = frozenset({"slope", "weather"})
#: Factors answered from the site's terrain facts on every request (TM05-143), never
#: stored. Enrichment, which writes stored results, runs before `make terrain`.
TERRAIN_FACTORS = frozenset({"drainage", "shelter", "view"})
NOT_STORED = ANALYSIS_CACHE_FACTORS | TERRAIN_FACTORS


def factors_digest(config: ScoringConfig | None = None) -> str:
    """Identifies everything a stored result depends on in the config: the model version and
    the factor settings. Not the weights, which only the combine reads."""
    config = config or load()
    canonical = json.dumps(
        {"model_version": config.model_version, "factors": config.factors},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]


def evaluate_stored(campsite, config: ScoringConfig | None = None) -> list[dict]:
    """The storable factor results for a campsite, stored-only, as JSON-ready dicts."""
    config = config or load()
    lon, lat = campsite.geom.x, campsite.geom.y
    return [
        asdict(factor.evaluate(lon, lat))
        for factor in build_factors(config, stored_only=True)
        if factor.key not in NOT_STORED
    ]


def terrain_results(campsite, config: ScoringConfig | None = None) -> dict[str, FactorResult]:
    """The terrain factors for a campsite, from its TerrainFacts (select_related
    "terrain" to avoid a query each). Empty when it has none: the factors then evaluate
    as not_available and drop out of the total."""
    from terrain.models import TerrainFacts

    try:
        facts = campsite.terrain
    except TerrainFacts.DoesNotExist:
        return {}
    config = config or load()
    return {
        factor.key: factor.from_facts(facts)
        for factor in build_factors(config, stored_only=True)
        if factor.key in TERRAIN_FACTORS
    }


def as_results(stored: list[dict]) -> dict[str, FactorResult]:
    """Stored dicts back into FactorResults, keyed by factor, for score_campsite()."""
    return {entry["key"]: FactorResult(**entry) for entry in stored}
