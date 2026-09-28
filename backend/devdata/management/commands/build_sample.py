"""
    python manage.py build_sample

Regenerates devdata/fixtures/sample.json from the live sources. Only needed when the
models or adapters change enough that the committed sample no longer loads or no longer
looks like real pipeline output -- day to day, everyone just runs `seed`.

Runs every keyless adapter (plus RIDB when RIDB_API_KEY is set) against the small
SAMPLE_AOI, then dumps what was written. Needs network access, and must run against an
empty scratch database so nothing but the sample ends up in the file -- a throwaway
container is ideal, see docs/deployment.md.

Fails rather than writing an incomplete sample. The dump goes to a temporary file first
and only replaces the committed fixture once every layer has rows and the file is within
MAX_FIXTURE_BYTES. An earlier version printed a warning and wrote the fixture anyway, and
a sample with no campsites went out: a new teammate seeded it, opened the app, and saw the
same empty map a real bug would show. A half-built sample is worse than none, because
nobody questions a fixture that loads cleanly.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from devdata.sample import (
    FIXTURE_PATH,
    KEYLESS_ADAPTERS,
    MAX_FIXTURE_BYTES,
    SAMPLE_AOI,
    dump_sample,
    empty_layers,
    feature_count,
)
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
            # Not a problem: campsites come from OSM. Said anyway so the log records it.
            self.stdout.write("RIDB_API_KEY not set: skipping Recreation.gov (optional).")

        for name in names:
            self.stdout.write(f"Ingesting {name} for {SAMPLE_AOI}...")
            run = get_adapter(name)().run(SAMPLE_AOI)
            self.stdout.write(f"  {run.get_status_display()}: {run.record_count} record(s)")

        pending = FIXTURE_PATH.with_name(FIXTURE_PATH.name + ".tmp")
        try:
            counts = dump_sample(pending)
            self._check(counts, pending.stat().st_size)
            pending.replace(FIXTURE_PATH)
        finally:
            pending.unlink(missing_ok=True)

        size_kb = FIXTURE_PATH.stat().st_size / 1024
        summary = ", ".join(f"{n} {label}" for label, n in counts.items())
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {FIXTURE_PATH.name} ({size_kb:.0f} KB): {summary}")
        )

    @staticmethod
    def _check(counts: dict[str, int], size: int) -> None:
        """Raise, leaving the committed fixture untouched, if the dump is not usable."""
        summary = ", ".join(f"{n} {label}" for label, n in counts.items())
        missing = empty_layers(counts)
        if missing:
            raise CommandError(
                f"Sample has no rows for {', '.join(missing)} ({summary}). A sample missing "
                f"a layer looks like a bug to whoever seeds it, so {FIXTURE_PATH.name} was "
                "not changed. Check the ingest output above for a source that returned "
                "nothing, or move SAMPLE_AOI in devdata/sample.py somewhere every layer "
                "has data."
            )
        if size > MAX_FIXTURE_BYTES:
            raise CommandError(
                f"Sample is {size / 1024:.0f} KB, over the {MAX_FIXTURE_BYTES / 1024:.0f} KB "
                f"budget for a committed file ({summary}), so {FIXTURE_PATH.name} was not "
                "changed. Shrink SAMPLE_AOI in devdata/sample.py."
            )
