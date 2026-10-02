"""
Derive location facts for every campsite in a configured region (TM05-64).

    python manage.py enrich_campsites adirondacks

Idempotent: re-running updates each campsite's CampsiteFacts row. Elevation and slope
are fetched for the whole region first in batched 3DEP requests (site_terrain's
run_many), and already-cached sites cost nothing. Prints runtime and per-fact coverage.
"""

import time

from django.contrib.gis.geos import Polygon
from django.core.management.base import BaseCommand, CommandError

from analysis.analyses.terrain import SiteTerrain
from enrichment.facts import enrich
from enrichment.models import CampsiteFacts
from geodata.models import Campsite
from pipeline.regions import RegionConfigError, get_region


class Command(BaseCommand):
    help = "Compute derived location facts for the campsites in a region."

    def add_arguments(self, parser):
        parser.add_argument("region")

    def handle(self, *args, region, **options):
        try:
            aoi = get_region(region)
        except RegionConfigError as error:
            raise CommandError(str(error)) from error
        box = Polygon.from_bbox(aoi.bbox)
        box.srid = 4326
        sites = list(Campsite.objects.filter(geom__intersects=box).order_by("id"))
        if not sites:
            self.stdout.write(f"No campsites in {region}.")
            return

        started = time.perf_counter()
        terrain = SiteTerrain().run_many([site.geom for site in sites])
        terrain_s = time.perf_counter() - started

        for site, outcome in zip(sites, terrain, strict=True):
            enrich(site, terrain=outcome)
        total_s = time.perf_counter() - started

        facts = CampsiteFacts.objects.filter(campsite__in=sites)
        n = len(sites)

        def pct(count):
            return f"{count} ({100 * count / n:.1f}%)"

        unnamed = sum(1 for site in sites if not (site.name or "").strip())
        derived = facts.filter(display_name_derived=True).count()
        self.stdout.write(
            f"{region}: {n} campsites in {total_s:.1f} s (terrain {terrain_s:.1f} s)\n"
            f"  public land unit   {pct(facts.exclude(land_name='').count())}\n"
            f"  named water        {pct(facts.exclude(water_distance_m=None).count())}\n"
            f"  named trail        {pct(facts.exclude(trail_distance_m=None).count())}"
            f"  (route {facts.filter(trail_kind='route').count()},"
            f" way {facts.filter(trail_kind='way').count()})\n"
            f"  elevation + slope  {pct(facts.exclude(slope_deg=None).count())}\n"
            f"  any OSM tag        {pct(facts.exclude(osm_tags={}).count())}\n"
            f"  shelter kind       {pct(facts.exclude(shelter_kind='').count())}\n"
            f"  display name       {pct(facts.exclude(display_name='').count())}"
            f"  (derived for {derived} of {unnamed} unnamed)"
        )
