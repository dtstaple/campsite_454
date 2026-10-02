"""
Benchmark nearest-water distance queries (TM05-42).

    python manage.py bench_distance [--runs 5] [--sites 150]

Runs each query shape against the same candidate set -- the first N campsites by id
inside the Adirondack box -- and reports the median EXPLAIN ANALYZE execution time over
`--runs` warm runs, plus whether the water table was reached by an index scan or a
sequential scan. The numbers in docs/architecture.md come from this command, so they can
be re-measured rather than trusted.

Read-only: the candidate set is a temporary table and nothing else is written.
"""

import re
import statistics

from django.core.management.base import BaseCommand
from django.db import connection

ADIRONDACKS = (-75.4, 43.0, -73.3, 44.9)

# name -> (description, SQL selecting one distance per candidate)
QUERIES = {
    "degrees_knn": (
        "before: KNN on the 4326 index (fast, but answers in degrees)",
        """SELECT c.id, n.d FROM bench_cand c CROSS JOIN LATERAL (
             SELECT ST_Distance(w.geom, c.geom) d FROM geodata_waterfeature w
             ORDER BY w.geom <-> c.geom LIMIT 1) n""",
    ),
    "geography_bbox_0.01": (
        "before: geography cast + 0.01 deg (~1 km) bbox prefilter (metres, slow)",
        """SELECT c.id, (SELECT min(ST_Distance(w.geom::geography, c.geom::geography))
             FROM geodata_waterfeature w WHERE w.geom && ST_Expand(c.geom, 0.01))
           FROM bench_cand c""",
    ),
    "geography_bbox_0.05": (
        "before: geography cast + 0.05 deg (~5 km) bbox prefilter",
        """SELECT c.id, (SELECT min(ST_Distance(w.geom::geography, c.geom::geography))
             FROM geodata_waterfeature w WHERE w.geom && ST_Expand(c.geom, 0.05))
           FROM bench_cand c""",
    ),
    "metric_knn": (
        "after: KNN on the 5070 geom_m index (metres, indexed)",
        """SELECT c.id, n.d FROM bench_cand c CROSS JOIN LATERAL (
             SELECT ST_Distance(w.geom_m, c.geom_m) d FROM geodata_waterfeature w
             ORDER BY w.geom_m <-> c.geom_m LIMIT 1) n""",
    ),
}


class Command(BaseCommand):
    help = "Measure nearest-water query times before and after the metric column."

    def add_arguments(self, parser):
        parser.add_argument("--runs", type=int, default=5)
        parser.add_argument("--sites", type=int, default=150)

    def handle(self, *args, runs, sites, **options):
        with connection.cursor() as cursor:
            cursor.execute(
                """CREATE TEMP TABLE bench_cand AS
                   SELECT id, geom, geom_m FROM geodata_campsite
                   WHERE geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                   ORDER BY id LIMIT %s""",
                [*ADIRONDACKS, sites],
            )
            cursor.execute("ANALYZE bench_cand")
            cursor.execute("SELECT count(*) FROM bench_cand")
            self.stdout.write(f"candidates: {cursor.fetchone()[0]} campsites, {runs} runs each\n")

            for name, (description, sql) in QUERIES.items():
                times, scan = [], "?"
                for _ in range(runs + 1):  # first run warms the cache and is discarded
                    cursor.execute(f"EXPLAIN (ANALYZE, FORMAT TEXT) {sql}")
                    plan = "\n".join(row[0] for row in cursor.fetchall())
                    times.append(float(re.search(r"Execution Time: ([\d.]+)", plan).group(1)))
                    scan = _water_scan(plan)
                median = statistics.median(times[1:])
                self.stdout.write(f"{name:22} {median:9.1f} ms  {scan:10}  {description}")

            cursor.execute("DROP TABLE bench_cand")


def _water_scan(plan: str) -> str:
    for line in plan.splitlines():
        if "geodata_waterfeature" in line:
            if "Seq Scan" in line:
                return "seq scan"
            if "Index" in line:
                return "index scan"
    return "?"
