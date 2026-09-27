"""
Delete trails that the tightened OSM query no longer ingests.

`load()` is an upsert by (source, source_id) and never deletes -- that is deliberate, and
it is what makes a re-run safe. But it also means tightening an ingestion filter does not
remove what a looser filter already loaded: re-ingesting the Adirondacks after excluding
sidewalks updated 18,067 rows and simply left the other 8,019 sitting there, still drawn
on the map. Every one of those 8,019 was a sidewalk, street crossing, traffic island,
access aisle or golf cart path.

A migration rather than a management command because the stale rows exist in every
database that ran the old ingest -- teammates' machines and CI included -- and this way
they go when everything else migrates, instead of depending on someone remembering.

The rule is spelled out here rather than imported from
`pipeline.adapters.osm_trails.is_hiking_trail`. A migration has to keep meaning the same
thing forever, and that function is free to change with the next tightening of the filter;
importing it would make this migration's effect depend on code written after it.
"""

from django.db import migrations
from django.db.models import Q

EXCLUDED_FOOTWAY_VALUES = ("sidewalk", "crossing", "traffic_island", "access_aisle")
EXCLUDED_IF_TAGGED = ("golf",)


def prune(apps, schema_editor):
    Trail = apps.get_model("geodata", "Trail")

    excluded = Q(raw__tags__footway__in=list(EXCLUDED_FOOTWAY_VALUES))
    for key in EXCLUDED_IF_TAGGED:
        excluded |= Q(raw__tags__has_key=key)

    Trail.objects.filter(excluded).delete()


def noop(apps, schema_editor):
    """Irreversible by design.

    The rows are not recoverable from here, and should not be: re-running the ingest is
    the way back, and the current query would not load them again anyway.
    """


class Migration(migrations.Migration):
    dependencies = [("geodata", "0004_backfill_publicland_gap_status")]

    operations = [migrations.RunPython(prune, noop)]
