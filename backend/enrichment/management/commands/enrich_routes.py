"""
Store derived facts for every named route in a region (TM05-85), for the Discover filters.

    python manage.py enrich_routes adirondacks [--fetch-profiles]

Gain and difficulty need the route's elevation profile. By default only cached profiles are
used (run build_route_profiles first for full coverage); --fetch-profiles computes missing
ones from 3DEP, which is slow. Route type and the nearest campsite need no profile.
"""

import time

from django.contrib.gis.geos import Polygon
from django.core.management.base import BaseCommand, CommandError

from analysis.analyses.elevation import RouteProfile
from analysis.base import AnalysisError
from enrichment.route_facts import save_route_facts
from geodata.models import TrailRoute
from pipeline.regions import RegionConfigError, get_region


class Command(BaseCommand):
    help = "Compute and store the Discover filter facts for a region's named routes."

    def add_arguments(self, parser):
        parser.add_argument("region")
        parser.add_argument("--fetch-profiles", action="store_true")

    def handle(self, *args, region, fetch_profiles, **options):
        try:
            aoi = get_region(region)
        except RegionConfigError as error:
            raise CommandError(str(error)) from error
        box = Polygon.from_bbox(aoi.bbox)
        box.srid = 4326
        routes = TrailRoute.objects.filter(geom__bboverlaps=box).exclude(name="")
        started = time.perf_counter()
        total = with_gain = 0
        for route in routes:
            profile = None
            if fetch_profiles:
                try:
                    profile = RouteProfile().run(route.geom).value
                except AnalysisError as error:
                    self.stderr.write(f"  no profile for {route.name}: {error}")
            facts = save_route_facts(route, profile)
            total += 1
            with_gain += facts.gain_m is not None
        self.stdout.write(
            f"{region}: {total} routes in {time.perf_counter() - started:.1f} s "
            f"({with_gain} with gain and difficulty, {total - with_gain} without a profile yet)"
        )
