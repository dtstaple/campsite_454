"""
Store every campsite's access difficulty from the nearest reachable trailhead (TM05-171).

Run after build_trail_graph and enrich_campsites; `make data` and `make refresh` do.
"""

from django.core.management.base import BaseCommand, CommandError

from pipeline.regions import RegionConfigError
from routing.access import CLASSES, LABELS
from routing.access_store import compute_region
from routing.service import PlanningError


class Command(BaseCommand):
    help = "Classify each campsite's access (easy, moderate, hard, unknown) from trailheads."

    def add_arguments(self, parser):
        parser.add_argument("region")

    def handle(self, *args, region, **options):
        try:
            summary = compute_region(region)
        except (RegionConfigError, PlanningError) as error:
            raise CommandError(str(error)) from error
        lines = [
            f"{region}: {summary.campsites} campsites, "
            f"{summary.trailheads_joined} of {summary.trailheads} trailheads on the graph"
        ]
        for name in CLASSES:
            lines.append(f"  {LABELS[name]:<16} {summary.by_class.get(name, 0)}")
        self.stdout.write("\n".join(lines) + "\n")
