"""
Terrain facts and zones for a region, from GeoLibre over 3DEP (TM05-141).

    python manage.py terrain adirondacks [--only wetness,viewshed] [--workers 3] [--fresh]

Runs every tool in terrain/tools.yml (docs/terrain-analysis.md). Resumable: finished
tiles are skipped under the same config and DEM, so re-running after an interruption
continues where it stopped, and re-running after a finished run only re-merges and
re-classifies. --fresh recomputes every tile. Prints per-tool runtime, peak memory,
campsite coverage and zone counts; the same numbers go into the TerrainRun record.
"""

from django.core.management.base import BaseCommand, CommandError

from pipeline.regions import RegionConfigError
from terrain import pipeline, registry


class Command(BaseCommand):
    help = "Compute terrain facts and zones for a region with GeoLibre."

    def add_arguments(self, parser):
        parser.add_argument("region")
        parser.add_argument("--only", default="", help="Comma-separated tool ids.")
        parser.add_argument("--workers", type=int, default=3)
        parser.add_argument("--fresh", action="store_true", help="Recompute every tile.")

    def handle(self, *args, region, only, workers, fresh, **options):
        tools = registry.load()
        names = [name.strip() for name in only.split(",") if name.strip()]
        unknown = [name for name in names if name not in tools.tools]
        if unknown:
            raise CommandError(f"Unknown tool(s) {unknown}; tools.yml has {list(tools.tools)}")
        try:
            run = pipeline.run(
                region,
                tools,
                only=names or None,
                workers=workers,
                fresh=fresh,
                log=self.stdout.write,
            )
        except RegionConfigError as error:
            raise CommandError(str(error)) from error

        timings, counts = run.timings, run.counts
        self.stdout.write(
            f"\n{region}: {counts['sites']} campsites, {timings['total_s']} s total "
            f"(prepare {timings['prepare_s']} s, zones {timings['merge_zones_s']} s, "
            f"classify {timings['classify_s']} s), peak RSS {run.peak_rss_mb} MB"
        )
        for tool, t in timings["tools"].items():
            self.stdout.write(
                f"  {tool:<10} {t['cpu_s']:>8} s over {t['tasks']} tasks "
                f"({t['skipped']} reused), peak WASM {t['peak_wasm_mb']} MB"
            )
        n = counts["sites"] or 1
        for fact, count in counts["coverage"].items():
            self.stdout.write(f"  {fact:<14} {count} ({100 * count / n:.1f}%)")
        for layer, classes in counts["zones"].items():
            self.stdout.write(f"  zones {layer}: {classes}")
