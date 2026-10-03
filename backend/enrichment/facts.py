"""
How each campsite fact is derived (TM05-64). One function per fact, each taking a
Campsite (or its point) and returning plain values, so each can be tested on its own.
`enrich()` puts them together; the enrich_campsites command runs it for a region.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q
from django.db.models.expressions import RawSQL
from django.utils import timezone

from analysis.analyses.terrain import SiteTerrain
from analysis.base import AnalysisError
from enrichment.models import CampsiteFacts
from geodata.distance import nearest
from geodata.models import Campsite, PublicLand, Trail, TrailRoute, WaterFeature

#: Bump when any derivation below changes meaning; stored with every row.
METHOD_VERSION = "1"

#: Beyond this, a feature is not "near" enough to describe the site.
MAX_NAMED_DISTANCE_M = 5000
#: A named route wins over a named OSM way unless the way is this much closer. Route
#: members are themselves ways, so on a route the two are usually the same distance.
ROUTE_PREFERENCE_M = 100
#: A derived name only uses a feature this close; past it "near" stops being honest.
DERIVED_NAME_MAX_M = 1000

#: OSM tags worth surfacing, minus those the adapter already reads into Campsite
#: (name, shelter_type, group_only, backcountry, reservation, capacity).
OSM_TAGS = (
    "operator",
    "description",
    "tents",
    "fireplace",
    "openfire",
    "toilets",
    "drinking_water",
    "shower",
    "fee",
    "access",
    "dog",
    "camp_site",
    "caravans",
    "cabins",
    "power_supply",
    "opening_hours",
    "wheelchair",
    "website",
    "phone",
    "ref",
)


# --- public land -----------------------------------------------------------------------


def public_land_unit(point):
    """The smallest parcel containing the point: a wilderness inside the Forest Preserve
    rather than the Forest Preserve. None outside every parcel."""
    return (
        PublicLand.objects.filter(geom__intersects=point)
        .annotate(area_m2=RawSQL("ST_Area(geom::geography)", []))
        .order_by("area_m2", "source_id")
        .first()
    )


# --- water ------------------------------------------------------------------------------


def nhd_name(water) -> str:
    """NHD's GNIS name. The adapter copies it into `name`, but the raw payload is the
    fallback: flowlines (layer 6) say `gnis_name`, waterbodies (layer 12) `GNIS_NAME`."""
    raw = water.raw or {}
    return (water.name or raw.get("gnis_name") or raw.get("GNIS_NAME") or "").strip()


# Positive lookups only: a negated JSON key lookup is NULL when the key is missing, which
# would silently drop every row that uses the other casing.
NAMED_WATER = Q(name__gt="") | Q(raw__gnis_name__gt="") | Q(raw__GNIS_NAME__gt="")


def nearest_named_water(lon, lat):
    feature = nearest(WaterFeature.objects.filter(NAMED_WATER), lon, lat)
    if feature is None or feature.distance_m > MAX_NAMED_DISTANCE_M or not nhd_name(feature):
        return None
    return feature


# --- trail ------------------------------------------------------------------------------


@dataclass
class NamedTrail:
    name: str
    distance_m: float
    kind: str  # "route" or "way"
    source_id: str


def nearest_named_trail(lon, lat) -> NamedTrail | None:
    """Prefer a named hiking route: it is what a hiker calls the trail. An OSM way's own
    name is used only when no route is near or the way is clearly closer."""
    route = nearest(TrailRoute.objects.exclude(name=""), lon, lat)
    way = nearest(Trail.objects.exclude(name=""), lon, lat)
    if route is not None and route.distance_m > MAX_NAMED_DISTANCE_M:
        route = None
    if way is not None and way.distance_m > MAX_NAMED_DISTANCE_M:
        way = None
    if route and (way is None or route.distance_m <= way.distance_m + ROUTE_PREFERENCE_M):
        return NamedTrail(route.name, route.distance_m, "route", route.source_id)
    if way:
        return NamedTrail(way.name, way.distance_m, "way", way.source_id)
    return None


# --- OSM tags ---------------------------------------------------------------------------


def osm_tags(campsite) -> tuple[dict, str]:
    """(extracted tags, shelter kind) from an OSM campsite's raw tags."""
    if campsite.source != Campsite.Source.OSM:
        return {}, ""
    tags = (campsite.raw or {}).get("tags") or {}
    extracted = {key: str(tags[key]).strip() for key in OSM_TAGS if str(tags.get(key, "")).strip()}
    if (tags.get("shelter_type") or "").lower() == "lean_to" or tags.get("amenity") == "shelter":
        kind = "lean-to"
    elif (tags.get("tents") or "").lower() == "yes":
        kind = "tent site"
    else:
        kind = ""
    return extracted, kind


# --- display name -----------------------------------------------------------------------


def display_name(campsite, water, trail: NamedTrail | None, land) -> tuple[str, bool]:
    """The source name if there is one. Otherwise "Campsite near <nearest named water or
    trail within 1 km>", or "Campsite in <public land unit>". Derived names are flagged."""
    if (campsite.name or "").strip():
        return campsite.name.strip(), False
    candidates = []
    if water is not None and water.distance_m <= DERIVED_NAME_MAX_M:
        candidates.append((water.distance_m, nhd_name(water)))
    if trail is not None and trail.distance_m <= DERIVED_NAME_MAX_M:
        candidates.append((trail.distance_m, trail.name))
    if candidates:
        return f"Campsite near {min(candidates)[1]}", True
    if land is not None and land.name:
        return f"Campsite in {land.name}", True
    return "", False


# --- putting it together ----------------------------------------------------------------


def enrich(campsite, terrain=None, now=None) -> CampsiteFacts:
    """Compute and upsert one campsite's facts. `terrain` is a site_terrain Outcome (or
    AnalysisError) when the caller batched 3DEP; otherwise it is fetched here."""
    now = now or timezone.now()
    lon, lat = campsite.geom.x, campsite.geom.y
    land = public_land_unit(campsite.geom)
    water = nearest_named_water(lon, lat)
    trail = nearest_named_trail(lon, lat)
    tags, kind = osm_tags(campsite)
    name, derived = display_name(campsite, water, trail, land)

    if terrain is None:
        try:
            terrain = SiteTerrain().run(campsite.geom)
        except AnalysisError as error:
            terrain = error
    terrain_value = None if isinstance(terrain, AnalysisError) else terrain.value

    facts, _ = CampsiteFacts.objects.update_or_create(
        campsite=campsite,
        defaults={
            "method_version": METHOD_VERSION,
            "computed_at": now,
            "land_name": land.name if land else "",
            "land_manager": land.manager if land else "",
            "land_designation": land.designation if land else "",
            "land_access": land.public_access if land else "",
            "land_gap_status": land.gap_status if land else "",
            "land_source_id": land.source_id if land else "",
            "water_name": nhd_name(water) if water else "",
            "water_distance_m": round(water.distance_m, 1) if water else None,
            "water_feature_type": water.feature_type if water else "",
            "water_perennial": water.perennial if water else None,
            "water_source_id": water.source_id if water else "",
            "trail_name": trail.name if trail else "",
            "trail_distance_m": round(trail.distance_m, 1) if trail else None,
            "trail_kind": trail.kind if trail else "",
            "trail_source_id": trail.source_id if trail else "",
            "elevation_m": terrain_value["elevation_m"] if terrain_value else None,
            "slope_deg": terrain_value["slope_deg"] if terrain_value else None,
            "slope_pct": terrain_value["slope_pct"] if terrain_value else None,
            "osm_tags": tags,
            "shelter_kind": kind,
            "display_name": name,
            "display_name_derived": derived,
            "provenance": {
                "method_version": METHOD_VERSION,
                "terrain": "site_terrain analysis (USGS 3DEP)"
                if terrain_value
                else f"unavailable: {terrain}",
                "max_named_distance_m": MAX_NAMED_DISTANCE_M,
                "route_preference_m": ROUTE_PREFERENCE_M,
                "derived_name_max_m": DERIVED_NAME_MAX_M,
            },
        },
    )
    return facts
