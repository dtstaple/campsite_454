"""
    python manage.py reset_db            # asks for confirmation
    python manage.py reset_db --noinput  # for scripts

Drops every table in the database's current schema, re-runs migrations, and loads the
sample dataset -- a clean, known state in one step, on any OS.

Only tables are dropped, never the schema or extensions. Tables that belong to an
extension (PostGIS's spatial_ref_sys) are left alone. That matters on hosted Postgres,
where the app's role usually cannot drop the public schema or create the PostGIS
extension itself; this command only needs the privileges migrate already needs.

Refuses to run when DEBUG is off unless --force is given, because a production database
should never be one mistyped DATABASE_URL away from being wiped.
"""

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# Tables in the current schema that no extension owns. pg_depend deptype 'e' marks an
# object as a member of an extension.
_APP_TABLES_SQL = """
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p')
      AND n.nspname = current_schema()
      AND NOT EXISTS (
          SELECT 1 FROM pg_depend d
          WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'
      )
    ORDER BY c.relname
"""


class Command(BaseCommand):
    help = "Drop all app tables, re-run migrations, and load the sample dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_false",
            dest="interactive",
            help="Do not ask for confirmation.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow running with DEBUG=False. Think twice.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "DEBUG is False, which suggests a production database. reset_db drops "
                "every table; pass --force if you really mean it."
            )

        target = self._describe_target()
        if options["interactive"]:
            answer = input(f"This will DROP every table in {target}. Type 'yes' to continue: ")
            if answer.strip().lower() != "yes":
                raise CommandError("Reset cancelled.")

        dropped = self._drop_app_tables()
        self.stdout.write(f"Dropped {dropped} table(s) in {target}.")

        call_command("migrate", interactive=False, verbosity=0)
        self.stdout.write("Migrations applied.")

        call_command("seed", stdout=self.stdout, stderr=self.stderr)

    @staticmethod
    def _describe_target() -> str:
        params = connection.settings_dict
        host = params.get("HOST") or "localhost"
        port = params.get("PORT") or "5432"
        return f"database '{params['NAME']}' on {host}:{port}"

    @staticmethod
    def _drop_app_tables() -> int:
        with connection.cursor() as cursor:
            cursor.execute(_APP_TABLES_SQL)
            tables = [row[0] for row in cursor.fetchall()]
            if tables:
                quoted = ", ".join(connection.ops.quote_name(t) for t in tables)
                cursor.execute(f"DROP TABLE {quoted} CASCADE")
        return len(tables)
