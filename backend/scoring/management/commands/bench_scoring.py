"""
Time the scoring engine on real campsites (TM05-43 AC: "scoring 100 sites completes in a
reasonable time, with the figure documented").

    python manage.py bench_scoring [--sites 100] [--runs 3]

Scores the first N campsites by id, `--runs` times after one discarded warm-up run, and
prints the median wall time plus the per-site mean. Read-only.
"""

import statistics
import time

from django.core.management.base import BaseCommand

from geodata.models import Campsite
from scoring.engine import score_campsite


class Command(BaseCommand):
    help = "Measure how long scoring N campsites takes."

    def add_arguments(self, parser):
        parser.add_argument("--sites", type=int, default=100)
        parser.add_argument("--runs", type=int, default=3)

    def handle(self, *args, sites, runs, **options):
        campsites = list(Campsite.objects.order_by("id")[:sites])
        times, scores = [], []
        for run in range(runs + 1):
            start = time.perf_counter()
            scores = [score_campsite(site)["score"] for site in campsites]
            elapsed = (time.perf_counter() - start) * 1000
            if run:  # the first run warms caches and is discarded
                times.append(elapsed)
        median = statistics.median(times)
        self.stdout.write(
            f"{len(campsites)} campsites: median {median:.0f} ms over {runs} runs "
            f"({median / len(campsites):.1f} ms per site); "
            f"scores min {min(scores)}, median {statistics.median(scores):g}, max {max(scores)}"
        )
