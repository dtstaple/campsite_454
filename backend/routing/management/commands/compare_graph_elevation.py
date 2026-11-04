"""
Compare the region's current graph elevations with the cached 3DEP mosaic (TM05-149).

    python manage.py compare_graph_elevation adirondacks [--trips 50] [--seed 149]

Run it after a build from 3DEP getSamples (`build_trail_graph <region> --elevation 3dep`)
and before switching to the mosaic. It prints a JSON report and fails when a tolerance in
routing.yml's `elevation_check` is exceeded. Nothing is written. docs/routing.md has the
measured figures.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from pipeline.regions import RegionConfigError, get_region
from routing.compare import compare, load_rows
from routing.elevation_source import choose


class Command(BaseCommand):
    help = "Compare the current graph's elevations with the cached 3DEP mosaic."

    def add_arguments(self, parser):
        parser.add_argument("region")
        parser.add_argument("--trips", type=int, default=50)
        parser.add_argument("--seed", type=int, default=149)

    def handle(self, *args, region, trips, seed, **options):
        try:
            choice = choose(region, get_region(region).bbox, mode="cache")
        except (RegionConfigError, FileNotFoundError) as error:
            raise CommandError(str(error)) from error
        rows = load_rows(region, choice.fetch)
        if not rows:
            raise CommandError(f"No graph has been built for {region}; run build_trail_graph.")
        report = compare(rows, trips=trips, seed=seed)
        report["mosaic"] = choice.provenance["mosaic"]
        self.stdout.write(json.dumps(report, indent=2))
        if not report["ok"]:
            failed = [name for name, ok in report["checks"].items() if not ok]
            raise CommandError(f"Outside tolerance: {', '.join(failed)}")
