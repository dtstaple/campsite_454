"""
Precompute elevation profiles for every named route in a region (TM05-67).

    python manage.py build_route_profiles adirondacks [--limit N]

Profiles are otherwise computed on first view (docs/elevation.md); running this after an
ingest means nobody waits on 3DEP in the trail panel. Cached routes cost nothing, so a
re-run only fetches what changed. Failures (3DEP down, a route with no usable geometry)
are counted and reported, never fatal.
"""

import time

from django.contrib.gis.geos import Polygon
from django.core.management.base import BaseCommand, CommandError

from analysis.analyses.elevation import RouteProfile
from analysis.base import AnalysisError
from geodata.models import TrailRoute
from pipeline.regions import RegionConfigError, get_region


class Command(BaseCommand):
    help = "Compute and cache elevation profiles for the named routes in a region."

    def add_arguments(self, parser):
        parser.add_argument("region")
        parser.add_argument("--limit", type=int, default=None, help="Only the N longest routes.")

    def handle(self, *args, region, limit, **options):
        try:
            aoi = get_region(region)
        except RegionConfigError as error:
            raise CommandError(str(error)) from error
        box = Polygon.from_bbox(aoi.bbox)
        box.srid = 4326
        routes = TrailRoute.objects.filter(geom__bboverlaps=box).exclude(name="")
        routes = list(
            routes.order_by("-length_m")[:limit] if limit else routes.order_by("-length_m")
        )

        started = time.perf_counter()
        computed = cached = failed = 0
        for route in routes:
            try:
                outcome = RouteProfile().run(route.geom)
            except AnalysisError as error:
                failed += 1
                self.stderr.write(f"  skipped {route.name} (relation/{route.osm_id}): {error}")
                continue
            if outcome.cached:
                cached += 1
            else:
                computed += 1
        self.stdout.write(
            f"{region}: {len(routes)} named routes in {time.perf_counter() - started:.1f} s "
            f"({computed} computed, {cached} already cached, {failed} failed)"
        )
