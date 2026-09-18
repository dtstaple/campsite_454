"""
    python manage.py ingest <source> <region>
    python manage.py ingest --list-sources
    python manage.py ingest --list-regions

The command knows nothing about any particular source. It resolves a name through the
adapter registry and a region through the config, so a new adapter becomes available here
the moment it registers itself.
"""

from django.core.management.base import BaseCommand, CommandError

from pipeline.adapters import get_adapter, list_adapters
from pipeline.adapters.registry import UnknownAdapterError
from pipeline.regions import RegionConfigError, get_region, list_regions


class Command(BaseCommand):
    help = "Run a registered source adapter against a configured region."

    def add_arguments(self, parser):
        parser.add_argument(
            "source",
            nargs="?",
            help="Registered adapter name. Use --list-sources to see them.",
        )
        parser.add_argument(
            "region",
            nargs="?",
            help="Configured region name. Use --list-regions to see them.",
        )
        parser.add_argument(
            "--list-sources",
            action="store_true",
            help="List registered adapters and exit.",
        )
        parser.add_argument(
            "--list-regions",
            action="store_true",
            help="List configured regions and exit.",
        )

    def handle(self, *args, **options):
        if options["list_sources"]:
            self._list_sources()
            return
        if options["list_regions"]:
            self._list_regions()
            return

        source = options["source"]
        region = options["region"]
        if not source or not region:
            raise CommandError(
                "Both <source> and <region> are required.\n"
                "  Usage: manage.py ingest <source> <region>\n"
                "  See:   manage.py ingest --list-sources | --list-regions"
            )

        try:
            adapter_cls = get_adapter(source)
        except UnknownAdapterError as exc:
            raise CommandError(str(exc)) from exc

        try:
            aoi = get_region(region)
        except RegionConfigError as exc:
            raise CommandError(str(exc)) from exc

        adapter = adapter_cls()
        self.stdout.write(f"Ingesting {adapter.name} for {aoi}...")

        run = adapter.run(aoi)

        summary = (
            f"{run.get_status_display()}: {run.record_count} record(s) "
            f"from {run.source} for {run.region} (run #{run.pk})"
        )
        if run.status == run.Status.SUCCESS:
            self.stdout.write(self.style.SUCCESS(summary))
        else:
            self.stdout.write(self.style.WARNING(summary))
            if run.notes:
                self.stdout.write(run.notes)

    def _list_sources(self):
        names = list_adapters()
        if not names:
            self.stdout.write(
                "No adapters registered yet. Real sources arrive in TM05-13; "
                "the framework itself is source-agnostic."
            )
            return
        self.stdout.write("Available sources:")
        for name in names:
            self.stdout.write(f"  {name}")

    def _list_regions(self):
        self.stdout.write("Available regions:")
        for name in list_regions():
            aoi = get_region(name)
            self.stdout.write(f"  {name:<20} {aoi.label:<22} bbox={aoi.bbox}")
