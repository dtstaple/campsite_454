"""
Full data rebuild for one region, every step timed (TM05-67). Used by `make data`.

    python scripts/build_data.py [--region adirondacks] [--only padus,osm-routes]

Steps, in dependency order: every ingest source, then named routes, then route elevation
profiles, then campsite enrichment (which reads all of the above). Each step runs
`manage.py` in a subprocess with live output; a summary table of durations prints at the
end. Stops at the first failing step and says which one.

RIDB is skipped without RIDB_API_KEY: it is optional, and federal-only, so the
Adirondacks (state land) have no RIDB campsites anyway.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANAGE = ROOT / "backend" / "manage.py"


def steps(region: str) -> list[tuple[str, list[str]]]:
    return [
        ("padus", ["ingest", "padus", region]),
        ("nhd-flowlines", ["ingest", "nhd-flowlines", region]),
        ("nhd-waterbodies", ["ingest", "nhd-waterbodies", region]),
        ("osm-trails", ["ingest", "osm-trails", region]),
        ("osm-campsites", ["ingest", "osm-campsites", region]),
        ("ridb", ["ingest", "ridb", region]),
        ("osm-routes", ["ingest", "osm-routes", region]),
        ("route-profiles", ["build_route_profiles", region]),
        ("enrich", ["enrich_campsites", region]),
    ]


def ridb_key() -> str:
    if os.environ.get("RIDB_API_KEY"):
        return os.environ["RIDB_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("RIDB_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--region", default="adirondacks")
    parser.add_argument("--only", default="", help="Comma-separated step names to run.")
    args = parser.parse_args()

    plan = steps(args.region)
    if args.only:
        wanted = {name.strip() for name in args.only.split(",") if name.strip()}
        unknown = wanted - {name for name, _ in plan}
        if unknown:
            print(
                f"Unknown step(s): {', '.join(sorted(unknown))}. "
                f"Steps: {', '.join(name for name, _ in plan)}"
            )
            return 2
        plan = [step for step in plan if step[0] in wanted]

    results: list[tuple[str, str, float]] = []
    total_start = time.perf_counter()
    for name, command in plan:
        if name == "ridb" and not ridb_key():
            print(f"\n=== {name}: SKIP (RIDB_API_KEY not set; optional)")
            results.append((name, "skipped", 0.0))
            continue
        print(f"\n=== {name}: manage.py {' '.join(command)}", flush=True)
        start = time.perf_counter()
        code = subprocess.call([sys.executable, str(MANAGE), *command], cwd=ROOT)
        elapsed = time.perf_counter() - start
        results.append((name, "ok" if code == 0 else f"FAILED ({code})", elapsed))
        print(f"=== {name}: {elapsed:.1f} s", flush=True)
        if code != 0:
            break

    total = time.perf_counter() - total_start
    print(f"\n{'step':<18}{'result':<14}{'seconds':>10}")
    for name, result, elapsed in results:
        print(f"{name:<18}{result:<14}{elapsed:>10.1f}")
    print(f"{'total':<18}{'':<14}{total:>10.1f}")
    failed = [name for name, result, _ in results if result.startswith("FAILED")]
    if failed:
        print(
            f"\nStopped at {failed[0]}. Re-run just that step with: " f"make data STEPS={failed[0]}"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
