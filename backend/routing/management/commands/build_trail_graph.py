"""
Build the routable trail graph for a region (TM05-119).

    python manage.py build_trail_graph adirondacks

Cuts the region's trail ways into edges at shared OSM nodes, measures each edge's climb
from 3DEP, and replaces the region's edges in one transaction. Run it after
`ingest osm-trails <region>`; docs/routing.md has the timings. Rebuilding is safe: the
old edges are dropped only once the new ones are ready.
"""

from django.core.management.base import BaseCommand, CommandError

from analysis.base import AnalysisError
from pipeline.regions import RegionConfigError
from routing.build import FETCH_WORKERS, SPACING_M, build_region


class Command(BaseCommand):
    help = "Build the routable trail graph for a region."

    def add_arguments(self, parser):
        parser.add_argument("region")
        parser.add_argument("--spacing", type=float, default=SPACING_M, help="Sample spacing, m.")
        parser.add_argument("--workers", type=int, default=FETCH_WORKERS)

    def handle(self, *args, region, spacing, workers, **options):
        try:
            build = build_region(region, spacing_m=spacing, workers=workers, log=self.stdout.write)
        except RegionConfigError as error:
            raise CommandError(str(error)) from error
        except AnalysisError as error:
            raise CommandError(f"3DEP failed, nothing was replaced: {error}") from error
        timing = build.provenance["timing_s"]
        self.stdout.write(
            f"{region}: {build.edges} edges, {build.nodes} nodes from {build.ways} ways "
            f"({build.ways_skipped} skipped); {build.elevation_samples} elevation samples "
            f"({build.elevation_nodata} no data); {timing['total']} s "
            f"(cut {timing['cut']} s, 3DEP {timing['climb']} s)"
        )
