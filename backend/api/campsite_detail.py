"""
GET /api/campsites/<source_id>/detail/ -- one campsite with its derived facts (TM05-64).

Additive: the map layers and TM05-45's scored endpoint are untouched. The id is the
campsite's source_id, the same string the map API uses as each Feature's id (it contains
a slash: "node/5759412256"). Unknown facts are null rather than placeholder text, so a
client can hide them; `facts` is null for a campsite that has not been enriched yet.
Contract: docs/api.md, "Campsite detail".
"""

from django.http import Http404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from enrichment.models import CampsiteFacts
from geodata.models import Campsite


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


@api_view(["GET"])
def campsite_detail_view(request, source_id: str):
    site = (
        Campsite.objects.filter(source_id=source_id).select_related("facts").order_by("pk").first()
    )
    if site is None:
        raise Http404(f"No campsite with source_id {source_id!r}")
    try:
        facts = site.facts
    except CampsiteFacts.DoesNotExist:
        facts = None

    source_name = (site.name or "").strip()
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
        }
    )
