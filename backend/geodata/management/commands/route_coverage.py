"""
Measure how much of the trail network named hiking routes cover (TM05-58).

    python manage.py route_coverage [region ...]

For each configured region (default: every region with trails ingested): how many
routes intersect it, and how much of the ingested trail length -- Trail ways inside the
region box -- belongs to at least one route. Membership is the route's member_way_ids
joined to Trail.source_id (`way/<id>`). Read-only.
"""

from django.core.management.base import BaseCommand
from django.db import connection

from pipeline.regions import load_regions

SQL = """
WITH env AS (SELECT ST_MakeEnvelope(%s, %s, %s, %s, 4326) AS g),
members AS (
    SELECT DISTINCT 'way/' || jsonb_array_elements_text(member_way_ids::jsonb) AS sid
    FROM geodata_trailroute
),
trails AS (
    SELECT t.length_m, t.source_id IN (SELECT sid FROM members) AS on_route
    FROM geodata_trail t, env WHERE t.geom && env.g
)
SELECT
    (SELECT count(*) FROM geodata_trailroute r, env WHERE r.geom && env.g),
    (SELECT count(*) FROM trails),
    (SELECT count(*) FROM trails WHERE on_route),
    (SELECT coalesce(sum(length_m), 0) FROM trails),
    (SELECT coalesce(sum(length_m), 0) FROM trails WHERE on_route)
"""


class Command(BaseCommand):
    help = "Report named-route coverage of the trail network per region."

    def add_arguments(self, parser):
        parser.add_argument("regions", nargs="*")

    def handle(self, *args, regions, **options):
        configured = load_regions()
        names = regions or list(configured)
        with connection.cursor() as cursor:
            for name in names:
                aoi = configured[name]
                cursor.execute(SQL, list(aoi.bbox))
                routes, ways, on_ways, length, on_length = cursor.fetchone()
                if not ways:
                    self.stdout.write(f"{name}: no trails ingested")
                    continue
                self.stdout.write(
                    f"{name}: {routes} routes; {on_length / 1000:,.0f} of {length / 1000:,.0f} km "
                    f"of trail on a route ({100 * on_length / length:.1f}%); "
                    f"{on_ways:,} of {ways:,} ways ({100 * on_ways / ways:.1f}%)"
                )
