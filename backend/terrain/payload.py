"""
Terrain facts as the API shows them (TM05-142): the campsite detail's `terrain` block,
the compact `terrain` badges on campsite rows, and the viewshed outline.

Every part is optional on its own. A fact the pipeline couldn't compute is null, not a
default. A campsite `make terrain` hasn't reached has no block at all.
"""

from __future__ import annotations

import json

from terrain.models import TerrainFacts

#: The caveat the app shows with every terrain fact.
NOTE = (
    "Terrain-model estimate from bare-earth elevation. "
    "Trees, buildings and recent changes aren't counted."
)


def _facts(site) -> TerrainFacts | None:
    try:
        return site.terrain
    except TerrainFacts.DoesNotExist:
        return None


def detail(site) -> dict | None:
    """The campsite detail's `terrain` block, or None before the site has terrain facts."""
    facts = _facts(site)
    if facts is None:
        return None
    view = None
    if facts.view_area_km2 is not None or facts.water_view is not None:
        view = {
            "area_km2": facts.view_area_km2,
            "direction": facts.view_direction or None,
            "water": facts.water_view,
        }
    return {
        "pooling": {"level": facts.pooling, "reason": facts.pooling_reason}
        if facts.pooling
        else None,
        "sun": {"facing": facts.facing, "label": facts.sun} if facts.facing else None,
        "shelter": {"level": facts.shelter, "reason": facts.shelter_reason}
        if facts.shelter
        else None,
        "view": view,
        "has_viewshed": facts.viewshed is not None,
        "note": NOTE,
        "computed_at": facts.computed_at.isoformat(),
    }


def badges(site) -> dict | None:
    """The compact form for list rows: pooling, shelter and water view only."""
    facts = _facts(site)
    if facts is None:
        return None
    return {
        "pooling": facts.pooling or None,
        "shelter": facts.shelter or None,
        "water_view": facts.water_view,
    }


def viewshed_feature(site) -> dict | None:
    """The site's viewshed as a GeoJSON Feature, or None."""
    facts = _facts(site)
    if facts is None or facts.viewshed is None:
        return None
    return {
        "type": "Feature",
        "id": site.source_id,
        "geometry": json.loads(facts.viewshed.json),
        "properties": {
            "area_km2": facts.view_area_km2,
            "direction": facts.view_direction or None,
            "water_view": facts.water_view,
            "note": NOTE,
        },
    }
