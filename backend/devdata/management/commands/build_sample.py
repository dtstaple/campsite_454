"""
    python manage.py build_sample

Regenerates devdata/fixtures/sample.json from the live sources. Only needed when the
models or adapters change enough that the committed sample no longer loads or no longer
looks like real pipeline output -- day to day, everyone just runs `seed`.

Runs every keyless adapter (plus RIDB when RIDB_API_KEY is set) against the small
SAMPLE_AOI, then dumps what was written. Needs network access, and must run against an
empty scratch database so nothing but the sample ends up in the file -- a throwaway
container is ideal, see docs/deployment.md.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from devdata.sample import FIXTURE_PATH, KEYLESS_ADAPTERS, SAMPLE_AOI, dump_sample, feature_count
from pipeline.adapters import get_adapter


class Command(BaseCommand):
    help = "Rebuild the committed sample fixture from live sources (needs network)."

    def handle(self, *args, **options):
        if feature_count():
            raise CommandError(
                "build_sample must run against an empty database, or rows outside the "
                "sample would be dumped too. Point DATABASE_URL at a scratch database."
            )

        names = list(KEYLESS_ADAPTERS)
        if os.environ.get("RIDB_API_KEY"):
            names.append("ridb")
        else:
            self.stdout.write(
                self.style.WARNING("RIDB_API_KEY not set: the sample will have no campsites.")
            )

        for name in names:
            self.stdout.write(f"Ingesting {name} for {SAMPLE_AOI}...")
            run = get_adapter(name)().run(SAMPLE_AOI)
            self.stdout.write(f"  {run.get_status_display()}: {run.record_count} record(s)")

        counts = dump_sample()
        size_kb = FIXTURE_PATH.stat().st_size / 1024
        summary = ", ".join(f"{n} {label}" for label, n in counts.items())
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {FIXTURE_PATH.name} ({size_kb:.0f} KB): {summary}")
        )
