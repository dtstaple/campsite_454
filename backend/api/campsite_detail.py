"""
GET /api/campsites/<source_id>/detail/ -- one campsite with its derived facts (TM05-64)
and its score (TM05-45).

The id is the campsite's source_id, the same string the map API uses as each Feature's id
(it contains a slash: "node/5759412256"). Unknown facts are null rather than placeholder
text, so a client can hide them; `facts` is null for a campsite that has not been enriched
yet.

The score is scored from stored values only: no 3DEP or Open-Meteo call is made on this
request, so a slope or forecast not already in the analysis cache is not_available rather
than fetched. The vector-data factors come from the results stored with the site's facts
(TM05-86, scoring/stored.py), the same ones the map's campsite layer combines. A campsite
that has not been enriched has no stored inputs and is not scored at all
(`score_status: "pending"`): its region usually has no vector data either, and scoring it
would report absent water and land as measured zeros.
Contract: docs/api.md, "Campsite detail".
"""

from django.http import Http404
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.authentication import OptionalTokenAuthentication
from accounts.weights import config_for
from enrichment.facts import stored_factor_results
from enrichment.models import CampsiteFacts
from geodata.confidence import confidence_payload
from geodata.models import Campsite
from scoring.config import ScoringConfig
from scoring.engine import ScoringError, score_campsite
from scoring.verdict import legality_verdict
from terrain import payload as terrain_payload

SCORED = "scored"
PENDING = "pending"
NOT_AVAILABLE = "not_available"


def _or_none(value):
    return value if value not in ("", None) else None


def public_land_payload(facts: CampsiteFacts | None) -> dict | None:
    """The public land unit containing the site, or None. Shared with the saved list
    (TM05-87), so both describe a site's land the same way."""
    if facts is None or not facts.land_name:
        return None
    return {
        "name": facts.land_name,
        "manager": _or_none(facts.land_manager),
        "designation": _or_none(facts.land_designation),
        "access": _or_none(facts.land_access),
        "gap_status": _or_none(facts.land_gap_status),
    }


def display_name_payload(site: Campsite, facts: CampsiteFacts | None) -> dict:
    """`display_name` and `display_name_derived`: the source name, or the derived one
    when the source has none. Shared with the saved list (TM05-87)."""
    source_name = (site.name or "").strip()
    return {
        "display_name": (facts.display_name if facts else source_name) or None,
        "display_name_derived": bool(facts and facts.display_name_derived),
    }


def _facts_payload(facts: CampsiteFacts) -> dict:
    return {
        "public_land": public_land_payload(facts),
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


def facts_of(site: Campsite) -> CampsiteFacts | None:
    try:
        return site.facts
    except CampsiteFacts.DoesNotExist:
        return None


def stored_score(
    site: Campsite, facts: CampsiteFacts | None, config: ScoringConfig | None = None
) -> tuple[str, dict | None]:
    """(score_status, contract-1 result or None). The one place a stored score is made:
    the map's campsite layer (TM05-86) and a route's campsite list (TM05-72) score through
    it too, so the three never disagree. `config` is the signed-in user's weights
    (TM05-46); None scores with the defaults."""
    if facts is None:
        return PENDING, None
    try:
        return SCORED, score_campsite(
            site, config, stored_only=True, evaluated=stored_factor_results(site, facts)
        )
    except ScoringError:
        return NOT_AVAILABLE, None


def score_payload(site: Campsite, config: ScoringConfig | None = None) -> dict:
    """`score` and `score_status` alone, for lists of campsites: the map's features
    (TM05-86) and the saved list (TM05-87). Select the site's facts with it."""
    status, result = stored_score(site, facts_of(site), config)
    return {"score": result["score"] if result else None, "score_status": status}


def stored_scores(ids: list[int], config: ScoringConfig | None = None) -> dict[int, dict]:
    """score_payload() for each Campsite primary key in `ids`."""
    sites = Campsite.objects.filter(pk__in=ids).select_related("facts")
    return {site.pk: score_payload(site, config) for site in sites}


@api_view(["GET"])
@authentication_classes([OptionalTokenAuthentication])
@permission_classes([AllowAny])
def campsite_detail_view(request, source_id: str):
    site = (
        Campsite.objects.filter(source_id=source_id)
        .select_related("facts", "last_run", "terrain")
        .order_by("pk")
        .first()
    )
    if site is None:
        raise Http404(f"No campsite with source_id {source_id!r}")
    facts = facts_of(site)

    source_name = (site.name or "").strip()
    score_status, result = stored_score(site, facts, config_for(request.user))
    return Response(
        {
            "id": site.source_id,
            "source": site.source,
            "name": source_name or None,
            **display_name_payload(site, facts),
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
            # Terrain-model facts from `make terrain` (TM05-142); null before it has run.
            "terrain": terrain_payload.detail(site),
        }
    )


@api_view(["GET"])
@authentication_classes([OptionalTokenAuthentication])
@permission_classes([AllowAny])
def campsite_viewshed_view(request, source_id: str):
    """GET /api/campsites/<source_id>/viewshed/ -- what the terrain lets you see from the
    site, as a GeoJSON Feature (TM05-142). Its own request: the outline is the one large
    part of the terrain facts, and the panel only needs it on "Show what I can see"."""
    site = (
        Campsite.objects.filter(source_id=source_id)
        .select_related("terrain")
        .order_by("pk")
        .first()
    )
    feature = terrain_payload.viewshed_feature(site) if site else None
    if feature is None:
        raise Http404(f"No viewshed for campsite {source_id!r}")
    return Response(feature)
