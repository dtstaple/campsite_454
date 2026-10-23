"""
    python manage.py refresh <region>          (make refresh REGION=<region>)

One command for a full data refresh of one region (TM05-91): every registered ingest
source, then route elevation profiles, then enrichment, in that order. It stops at the
first step that fails, and always prints a per-step summary: status, seconds, and the
record count from the IngestRun rows the step wrote.

The sources come from the adapter registry, the same list `ingest --list-sources` prints,
so a newly registered adapter is refreshed without editing this file. `INGEST_ORDER` only
settles the order of the ones that have one; any other source runs after them.

RIDB is skipped without RIDB_API_KEY: it is optional, and federal-only, so the
Adirondacks (state land) have no RIDB campsites anyway.
"""

import os
import time
from dataclasses import dataclass

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from geodata.models import IngestRun
from pipeline.adapters import list_adapters
from pipeline.regions import RegionConfigError, get_region

# Dependency order for the sources that have one: land and water first, then trails, then
# what is read against them. `osm-routes` joins its member ways to `osm-trails` rows.
INGEST_ORDER = (
    "padus",
    "nhd-flowlines",
    "nhd-waterbodies",
    "osm-trails",
    "osm-campsites",
    "osm-landmarks",
    "ridb",
    "osm-routes",
    # TM05-137: roads between trails, for the routing graph's road walks.
    "osm-connectors",
)

# After every ingest, in order: profiles read the routes, campsite enrichment reads every
# layer, and route facts read the profiles.
DERIVED_STEPS: tuple[tuple[str, str], ...] = (
    # TM05-119/137: the routing graph, from the trails and the roads between them.
    ("trail-graph", "build_trail_graph"),
    ("route-profiles", "build_route_profiles"),
    ("enrich", "enrich_campsites"),
    ("route-facts", "enrich_routes"),
)

OK, SKIPPED, FAILED = "ok", "skipped", "FAILED"


@dataclass
class StepResult:
    name: str
    status: str
    seconds: float = 0.0
    #: Rows the step's IngestRun(s) recorded. None for a step that writes no IngestRun.
    records: int | None = None
    detail: str = ""


def ingest_sources() -> list[str]:
    """Every registered source: the ordered ones first, then any other, alphabetically."""
    registered = list_adapters()
    ordered = [name for name in INGEST_ORDER if name in registered]
    return ordered + sorted(name for name in registered if name not in INGEST_ORDER)


class Command(BaseCommand):
    help = "Refresh one region: every ingest source, route profiles, then enrichment."

    def add_arguments(self, parser):
        parser.add_argument("region", help="Configured region name, e.g. adirondacks.")

    def handle(self, *args, **options):
        region = options["region"]
        try:
            get_region(region)
        except RegionConfigError as exc:
            raise CommandError(str(exc)) from exc

        plan = [(name, ["ingest", name, region]) for name in ingest_sources()]
        plan += [(name, [command, region]) for name, command in DERIVED_STEPS]

        results: list[StepResult] = []
        total_start = time.perf_counter()
        for name, command in plan:
            if name == "ridb" and not os.environ.get("RIDB_API_KEY"):
                self.stdout.write(f"\n=== {name}: SKIP (RIDB_API_KEY not set; optional)")
                results.append(StepResult(name, SKIPPED, detail="RIDB_API_KEY not set"))
                continue
            self.stdout.write(f"\n=== {name}: manage.py {' '.join(command)}")
            results.append(self.run_step(name, command, region))
            if results[-1].status == FAILED:
                break

        self.print_summary(results, time.perf_counter() - total_start)

        if results[-1].status == FAILED:
            not_run = [name for name, _ in plan[len(results) :]]
            message = f"Stopped at {results[-1].name}: {results[-1].detail}"
            if not_run:
                message += f"\nNot run: {', '.join(not_run)}"
            raise CommandError(message)

    def run_step(self, name: str, command: list[str], region: str) -> StepResult:
        """Run one step in this process, timing it and reading back what it recorded."""
        last_run_id = IngestRun.objects.order_by("-id").values_list("id", flat=True).first() or 0
        start = time.perf_counter()
        try:
            call_command(*command, stdout=self.stdout, stderr=self.stderr)
            status, detail = OK, ""
        # A failed step must not lose the summary of the ones before it, whatever it raised.
        except Exception as exc:
            status, detail = FAILED, f"{type(exc).__name__}: {exc}"
        seconds = time.perf_counter() - start

        # The IngestRun rows this step wrote. A failed ingest still writes one, with
        # however many rows it had recorded, so the count is read on both paths.
        runs = IngestRun.objects.filter(id__gt=last_run_id, region=region)
        records = runs.aggregate(total=Sum("record_count"))["total"] if runs.exists() else None
        statuses = sorted(set(runs.values_list("status", flat=True)))
        if status == OK and statuses:
            detail = "IngestRun: " + ", ".join(statuses)
        return StepResult(name, status, seconds, records, detail)

    def print_summary(self, results: list[StepResult], total_seconds: float) -> None:
        self.stdout.write(f"\n{'step':<18}{'result':<10}{'seconds':>10}{'records':>10}  notes")
        for result in results:
            records = "-" if result.records is None else f"{result.records:,}"
            self.stdout.write(
                f"{result.name:<18}{result.status:<10}{result.seconds:>10.1f}{records:>10}"
                f"  {result.detail}".rstrip()
            )
        total_records = sum(result.records or 0 for result in results)
        self.stdout.write(f"{'total':<18}{'':<10}{total_seconds:>10.1f}{total_records:>10,}")
