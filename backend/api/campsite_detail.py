"""
GET /api/campsites/<source_id>/detail/ -- one campsite with its derived facts (TM05-64)
and its score (TM05-45).

The id is the campsite's source_id, the same string the map API uses as each Feature's id
(it contains a slash: "node/5759412256"). Unknown facts are null rather than placeholder
text, so a client can hide them; `facts` is null for a campsite that has not been enriched
yet.

The score is scored from stored values only: no 3DEP or Open-Meteo call is made on this
request, so a slope or forecast not already in the analysis cache is not_available rather
than fetched. A campsite that has not been enriched has no stored inputs and is not scored
at all (`score_status: "pending"`): its region usually has no vector data either, and
scoring it would report absent water and land as measured zeros.
Contract: docs/api.md, "Campsite detail".
"""

from django.http import Http404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from enrichment.models import CampsiteFacts
from geodata.confidence import confidence_payload
from geodata.models import Campsite
from scoring.engine import ScoringError, score_campsite
from scoring.verdict import legality_verdict

SCORED = "scored"
PENDING = "pending"
NOT_AVAILABLE = "not_available"


def _or_none(value):
    return value if value not in ("", None) else None


def _facts_payload(facts: CampsiteFacts) -> dict:
    return {
        "public_land": {
            "name": facts.land_name,
            "manager": _or_none(facts.land_manager),
            "designation": _or_none(facts.land_designation),
            "access": _or_none(facts.land_access),
            "gap_status": _or_none(facts.land_gap_status),
        }
        if facts.land_name
        else None,
        "water": {
            "name": facts.water_name,
            "distance_m": facts.water_distance_m,
            "feature_type": _or_none(facts.water_feature_type),
            "perennial": facts.water_perennial,
        }
        if facts.water_distance_m is not None
        else None,
        "trail": {
            "name": facts.trail_name,
            "distance_m": facts.trail_distance_m,
            "kind": facts.trail_kind,
        }
        if facts.trail_distance_m is not None
        else None,
        "terrain": {
            "elevation_m": facts.elevation_m,
            "slope_deg": facts.slope_deg,
            "slope_pct": facts.slope_pct,
        }
        if facts.slope_deg is not None
        else None,
        "amenities": {"shelter_kind": _or_none(facts.shelter_kind), "osm_tags": facts.osm_tags},
        "method_version": facts.method_version,
        "computed_at": facts.computed_at.isoformat(),
    }


def _score(site: Campsite, facts: CampsiteFacts | None) -> tuple[str, dict | None]:
    """(score_status, contract-1 result or None)."""
    if facts is None:
        return PENDING, None
    try:
        return SCORED, score_campsite(site, stored_only=True)
    except ScoringError:
        return NOT_AVAILABLE, None


@api_view(["GET"])
def campsite_detail_view(request, source_id: str):
    site = (
        Campsite.objects.filter(source_id=source_id)
        .select_related("facts", "last_run")
        .order_by("pk")
        .first()
    )
    if site is None:
        raise Http404(f"No campsite with source_id {source_id!r}")
    try:
        facts = site.facts
    except CampsiteFacts.DoesNotExist:
        facts = None

    source_name = (site.name or "").strip()
    score_status, result = _score(site, facts)
    return Response(
        {
            "id": site.source_id,
            "source": site.source,
            "name": source_name or None,
            "display_name": (facts.display_name if facts else source_name) or None,
            "display_name_derived": bool(facts and facts.display_name_derived),
            "site_type": site.site_type,
            "reservable": site.reservable,
            "lon": round(site.geom.x, 6),
            "lat": round(site.geom.y, 6),
            "facts": _facts_payload(facts) if facts else None,
            "score": result["score"] if result else None,
            "score_status": score_status,
            "score_breakdown": result,
            # How far to trust this record, and when it was last ingested (TM05-77).
            "confidence": confidence_payload(site),
            # The legality verdict shown above the score (TM05-76 follow-up).
            "legality": legality_verdict(site, facts, result["legal_status"] if result else None),
        }
    )
