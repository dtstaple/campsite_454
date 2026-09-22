"""
    python manage.py seed

Loads the committed sample dataset (devdata/fixtures/sample.json) into whatever database
DATABASE_URL points at. Plain Python, so it runs the same on macOS, Windows, and Linux.

Refuses to run against a database that already holds features. Fixture rows carry fixed
primary keys, so loading them over real data would silently overwrite whichever rows
happen to share those keys. To start over, use `manage.py reset_db`.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from devdata.sample import FEATURE_MODELS, FIXTURE_PATH, feature_count


class Command(BaseCommand):
    help = "Load the small committed sample dataset into an empty database."

    def handle(self, *args, **options):
        if not FIXTURE_PATH.exists():
            raise CommandError(f"Sample fixture not found at {FIXTURE_PATH}.")

        existing = feature_count()
        if existing:
            raise CommandError(
                f"The database already contains {existing} feature(s), so seeding could "
                "overwrite real rows. Run `python manage.py reset_db` to drop everything "
                "and re-seed from scratch."
            )

        with transaction.atomic():
            call_command("loaddata", str(FIXTURE_PATH), verbosity=0)

        counts = ", ".join(
            f"{m.objects.count()} {m._meta.verbose_name_plural}" for m in FEATURE_MODELS
        )
        self.stdout.write(self.style.SUCCESS(f"Seeded sample dataset: {counts}."))
