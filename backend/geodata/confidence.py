"""
How much to trust a campsite record (TM05-77): a confidence level from where the record
came from and how much it says, plus its provenance. docs/confidence.md has the rules.

    official           listed in an official dataset: Recreation.gov (RIDB). Only RIDB.
    community_mapped   mapped by OpenStreetMap contributors, with a name or enough detail.
                       Stays community-mapped even when tagged operator=NYSDEC: the tag is
                       a contributor's claim, not the agency's own list. The operator is
                       reported separately.
    limited_info       an OpenStreetMap site with no name and fewer than
                       MIN_INFORMATIVE_TAGS informative tags: somebody marked a spot, and
                       little more is known.
    computed           not a record at all: a potential spot computed from land, trail,
                       water, elevation and slope data (TM05-99). Nobody has mapped a
                       campsite there. Always labelled "Potential spot (unverified)".

The level describes the record, not the site: a well-used spot can be limited_info simply
because nobody has tagged it.
"""

from __future__ import annotations

from enrichment.facts import OSM_TAGS
from geodata.models import Campsite

OFFICIAL = "official"
COMMUNITY_MAPPED = "community_mapped"
LIMITED_INFO = "limited_info"
COMPUTED = "computed"

LABELS = {
    OFFICIAL: "Official listing",
    COMMUNITY_MAPPED: "Community-mapped",
    LIMITED_INFO: "Limited info",
    COMPUTED: "Computed",
}

COMPUTED_REASON = (
    "Computed from public land, trail, water, elevation and slope data. Nobody has mapped "
    "a campsite here."
)


def computed_payload() -> dict:
    """The `confidence` object for a potential campsite (TM05-99): same shape as a mapped
    campsite's, so the panel reads both the same way."""
    return {
        "level": COMPUTED,
        "label": LABELS[COMPUTED],
        "reason": COMPUTED_REASON,
        "source": "computed",
        "source_label": "CampSite candidate search",
        "operator": None,
        "last_updated": None,
    }


#: Tags that say something about the site. OSM_TAGS (what the panel surfaces) plus the
#: ones the adapter reads into Campsite fields. `tourism`, `amenity` and `name` are not
#: counted: every record has the first two, and the name is checked on its own.
INFORMATIVE_TAGS = frozenset(OSM_TAGS) | {
    "shelter_type",
    "group_only",
    "backcountry",
    "reservation",
    "capacity",
}

#: An unnamed OSM site needs at least this many informative tags to be community_mapped.
MIN_INFORMATIVE_TAGS = 2


def osm_tags(site: Campsite) -> dict:
    tags = (site.raw or {}).get("tags")
    return tags if isinstance(tags, dict) else {}


def informative_tag_count(tags: dict) -> int:
    return sum(1 for key, value in tags.items() if key in INFORMATIVE_TAGS and str(value).strip())


def confidence_level(site: Campsite) -> tuple[str, str]:
    """(level, reason) for one campsite record."""
    if site.source == Campsite.Source.RIDB:
        return OFFICIAL, "Listed by Recreation.gov, the federal reservation system."
    if site.source != Campsite.Source.OSM:
        return LIMITED_INFO, "From a source with no confidence rule yet."
    count = informative_tag_count(osm_tags(site))
    if (site.name or "").strip() or count >= MIN_INFORMATIVE_TAGS:
        return COMMUNITY_MAPPED, "Mapped by OpenStreetMap contributors."
    detail = "no other details" if count == 0 else "one other detail"
    return LIMITED_INFO, f"Mapped by an OpenStreetMap contributor with no name and {detail}."


def confidence_payload(site: Campsite) -> dict:
    """The detail endpoint's `confidence` object: level, why, where from, and when."""
    level, reason = confidence_level(site)
    tags = osm_tags(site)
    run = site.last_run
    updated = (run.finished_at or run.started_at) if run else site.updated_at
    return {
        "level": level,
        "label": LABELS[level],
        "reason": reason,
        "source": site.source,
        "source_label": Campsite.Source(site.source).label,
        # Who the source says runs it: separate from the level on purpose.
        "operator": (tags.get("operator") or "").strip() or None,
        "last_updated": updated.isoformat() if updated else None,
    }
