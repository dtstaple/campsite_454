"""
Dump and restore the team data snapshot against any DATABASE_URL (TM05-160).

    python scripts/snapshot.py restore <path-or-url> [--force] [--if-empty]
    python scripts/snapshot.py dump [--out dumps/campsite-<date>.dump]
    python scripts/snapshot.py check <dump-file>

`make restore` and `make dump` call this. It works the same for all three development paths
in docs/setup.md: the local Docker database, the dev container's `db` service, and a hosted
PostGIS (with `?sslmode=require`). The target is DATABASE_URL from the environment, else
from the repo's .env.

restore
  Refuses a database that already holds data unless --force is given, because a restore
  replaces every table in the `public` schema. --if-empty turns that refusal into a quiet
  skip, which the dev container uses on every rebuild. It creates the PostGIS extension when
  it is missing, restores, then runs Django's migrations so an older snapshot is brought up
  to the current schema.

dump
  Writes the public schema with every person's data left out (PERSONAL_TABLES: accounts,
  tokens, sessions, admin log, saved campsites, waypoints, trip plans, hikes and saved
  trails are dumped as empty tables), then checks the result with `check`.

check
  Lists which tables a dump holds rows for, and fails if any personal table has data.

The snapshot is a PostgreSQL 16 custom-format dump, which older pg_restore versions cannot
read. pg_dump/pg_restore 16+ are used when installed; otherwise they run inside the
postgis/postgis:16-3.4 image (the same one as CI and docker-compose.yml) through Docker.
Connection details reach the tools as PG* environment variables, so a password never
appears on a command line.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
DUMPS = ROOT / "dumps"
TOOLS_IMAGE = "postgis/postgis:16-3.4"
MIN_TOOLS_MAJOR = 16

# Data that belongs to a person, not the project: dumped as empty tables. Patterns, so a new
# per-user table in accounts or planning is left out automatically. Every planning table is a
# user's own (waypoints, trip plans and their stops, hikes, saved trails).
# tests/test_snapshot.py checks that every model pointing at a user matches one of these.
PERSONAL_TABLES = (
    "auth_user",
    "auth_user_groups",
    "auth_user_user_permissions",
    "authtoken_token",
    "accounts_*",
    "planning_*",
    "django_session",
    "django_admin_log",
)

# Tables `make setup`'s migrate fills by itself. A database holding only these is "empty".
MIGRATE_ONLY_TABLES = {
    "spatial_ref_sys",
    "django_migrations",
    "django_content_type",
    "auth_permission",
}

# Libpq URL query parameters passed on as PG* environment variables.
QUERY_ENV = {
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "options": "PGOPTIONS",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "application_name": "PGAPPNAME",
}

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


class SnapshotError(Exception):
    """A failure with a message that says what to do about it."""


# --- the target database -------------------------------------------------------------------


def database_url(environ: dict[str, str] | None = None) -> str:
    """DATABASE_URL from the environment, else from the repo's .env."""
    environ = os.environ if environ is None else environ
    if environ.get("DATABASE_URL"):
        return environ["DATABASE_URL"]
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip() == "DATABASE_URL" and value.strip():
                return value.strip()
    raise SnapshotError("DATABASE_URL is not set. FIX: make setup (creates .env), or export it.")


def pg_env(url: str) -> dict[str, str]:
    """A postgres/postgis URL as libpq's PG* variables."""
    parts = urlsplit(url)
    if parts.scheme not in ("postgres", "postgresql", "postgis", "pgsql"):
        raise SnapshotError(f"DATABASE_URL must be a postgres:// URL, not {parts.scheme}://")
    env = {
        "PGHOST": parts.hostname or "localhost",
        "PGPORT": str(parts.port or 5432),
        "PGUSER": unquote(parts.username or ""),
        "PGPASSWORD": unquote(parts.password or ""),
        "PGDATABASE": unquote(parts.path.lstrip("/")),
    }
    if not env["PGDATABASE"]:
        raise SnapshotError("DATABASE_URL names no database (it should end in /<name>).")
    for key, value in parse_qsl(parts.query):
        if key in QUERY_ENV:
            env[QUERY_ENV[key]] = value
    return {key: value for key, value in env.items() if value}


def describe(env: dict[str, str]) -> str:
    """The target without its password, for messages."""
    ssl = f" sslmode={env['PGSSLMODE']}" if "PGSSLMODE" in env else ""
    return f"{env.get('PGUSER', '?')}@{env['PGHOST']}:{env['PGPORT']}/{env['PGDATABASE']}{ssl}"


def connect(env: dict[str, str]):
    import psycopg2

    params = {
        "host": env["PGHOST"],
        "port": env["PGPORT"],
        "user": env.get("PGUSER"),
        "password": env.get("PGPASSWORD"),
        "dbname": env["PGDATABASE"],
        "sslmode": env.get("PGSSLMODE"),
        "sslrootcert": env.get("PGSSLROOTCERT"),
        "connect_timeout": env.get("PGCONNECT_TIMEOUT", "15"),
    }
    try:
        connection = psycopg2.connect(**{k: v for k, v in params.items() if v})
    except psycopg2.OperationalError as error:
        raise SnapshotError(
            f"cannot connect to {describe(env)}: {str(error).strip()}\n"
            "FIX: check DATABASE_URL; run make doctor for the database checks."
        ) from error
    connection.autocommit = True
    return connection


def non_empty_tables(connection) -> list[str]:
    """Tables in `public` that hold rows, ignoring what migrate fills by itself."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = sorted(row[0] for row in cursor.fetchall())
        found = []
        for table in tables:
            if table in MIGRATE_ONLY_TABLES:
                continue
            cursor.execute(f'SELECT EXISTS (SELECT 1 FROM public."{table}")')
            if cursor.fetchone()[0]:
                found.append(table)
    return found


def ensure_postgis(connection) -> str:
    import psycopg2

    with connection.cursor() as cursor:
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        row = cursor.fetchone()
        if row:
            return f"PostGIS {row[0]} already installed"
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        except psycopg2.Error as error:
            raise SnapshotError(
                f"PostGIS is missing and could not be created: {str(error).strip()}\n"
                "FIX: enable PostGIS once as the database's admin role (the provider's SQL "
                "console: CREATE EXTENSION postgis;), or choose a provider that offers it "
                "(docs/setup.md, path C)."
            ) from error
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        return f"PostGIS {cursor.fetchone()[0]} created"


def drop_public_tables(connection) -> int:
    """Drop every table in `public` except PostGIS's own, so the restore starts clean.

    Dropping, rather than pg_restore --clean, also removes tables a newer migrate created
    that the snapshot does not know about; otherwise the migrate after the restore would
    try to create them again and fail.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename <> 'spatial_ref_sys'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(f'DROP TABLE IF EXISTS public."{table}" CASCADE')
    return len(tables)


# What a restore reports, so a run log shows what arrived.
SUMMARY_TABLES = {
    "geodata_campsite": "campsites",
    "geodata_trail": "trails",
    "geodata_trailroute": "named routes",
    "geodata_waterfeature": "water features",
    "geodata_publicland": "public land",
    "geodata_landmark": "peaks and trailheads",
    "enrichment_campsitefacts": "campsite facts",
    "routing_trailedge": "routing graph edges",
    "terrain_terrainfacts": "terrain facts",
    "terrain_terrainzone": "terrain zones",
}


def summary(connection) -> str:
    """Row counts of the main tables, as one line each; a missing table reads 'absent'."""
    lines = []
    with connection.cursor() as cursor:
        for table, label in SUMMARY_TABLES.items():
            cursor.execute("SELECT to_regclass(%s)", [f"public.{table}"])
            if cursor.fetchone()[0] is None:
                lines.append(f"    {label:22} absent")
                continue
            cursor.execute(f'SELECT count(*) FROM public."{table}"')
            lines.append(f"    {label:22} {cursor.fetchone()[0]:>9,}")
    return "\n".join(lines)


# --- pg_dump / pg_restore ------------------------------------------------------------------


def tools_major(binary: str) -> int | None:
    path = shutil.which(binary)
    if not path:
        return None
    result = subprocess.run([path, "--version"], capture_output=True, text=True, check=False)
    match = re.search(r"(\d+)(?:\.\d+)?", result.stdout)
    return int(match.group(1)) if match else None


class Tools:
    """Runs pg_dump/pg_restore 16+ locally, or inside the PostGIS image with Docker."""

    def __init__(self, env: dict[str, str], workdir: Path, mode: str | None = None):
        self.env = env
        self.workdir = workdir.resolve()
        self.mode = mode or self.pick()

    @staticmethod
    def pick() -> str:
        if (tools_major("pg_restore") or 0) >= MIN_TOOLS_MAJOR:
            return "local"
        if shutil.which("docker"):
            return "docker"
        raise SnapshotError(
            "Needs pg_dump/pg_restore 16 or newer, or Docker to run them.\n"
            "FIX: macOS: brew install libpq (then add its bin to PATH), or start Docker. "
            "Ubuntu: sudo apt install postgresql-client-16 (from apt.postgresql.org)."
        )

    def command(self, args: list[str]) -> tuple[list[str], dict[str, str]]:
        """The command line and environment for one tool call. File arguments are names
        inside workdir, which is the working directory locally and /work in Docker."""
        if self.mode == "local":
            return args, {**os.environ, **self.env}
        env = dict(self.env)
        if env.get("PGHOST") in LOCAL_HOSTS:
            env["PGHOST"] = "host.docker.internal"  # the host machine, seen from the container
        docker = ["docker", "run", "--rm", "--add-host=host.docker.internal:host-gateway"]
        docker += ["-v", f"{self.workdir}:/work", "-w", "/work"]
        if hasattr(os, "getuid"):
            docker += ["--user", f"{os.getuid()}:{os.getgid()}"]
        for key in env:
            docker += ["-e", key]  # the value comes from the environment, not the argv
        return docker + [TOOLS_IMAGE, *args], {**os.environ, **env}

    def run(self, args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
        command, env = self.command(args)
        result = subprocess.run(
            command, env=env, cwd=self.workdir, capture_output=capture, text=True, check=False
        )
        if result.returncode != 0:
            detail = (result.stderr or "").strip()[-2000:] if capture else ""
            raise SnapshotError(f"{args[0]} failed (exit {result.returncode}). {detail}".strip())
        return result


def toc_lines(tools: Tools, dump_name: str) -> list[str]:
    return tools.run(["pg_restore", "--list", dump_name], capture=True).stdout.splitlines()


def restore_list(lines: list[str], no_terrain: bool = False) -> list[str]:
    """The table of contents to restore. Left out: the `public` schema's own entries, which
    every database already has and which PostGIS lives in, and comments on extensions, which
    only a superuser may set (a managed host such as Render refuses them, TM05-113).

    no_terrain restores every terrain table empty, for a hosted free tier too small for the
    whole snapshot (docs/setup.md, path C). It is all of them or none: the facts, tiles and
    zones point at their TerrainRun, and the app decides whether terrain was checked from
    TerrainRun, so leaving only the zones out would make the pooling check pass everywhere.
    Without any terrain rows the app says "not checked" instead, which is true.
    """
    skipped = (" SCHEMA - public ", " COMMENT - SCHEMA public ", " COMMENT - EXTENSION ")
    if no_terrain:
        skipped += (" TABLE DATA public terrain_",)
    return [line for line in lines if not any(entry in line for entry in skipped)]


def data_tables(lines: list[str]) -> list[str]:
    """Tables a dump holds rows for: its TABLE DATA entries."""
    found = []
    for line in lines:
        match = re.search(r" TABLE DATA (\S+) (\S+) ", line)
        if match:
            found.append(match.group(2))
    return found


def personal(table: str) -> bool:
    return any(fnmatch.fnmatchcase(table, pattern) for pattern in PERSONAL_TABLES)


# --- commands ------------------------------------------------------------------------------


def fetch(source: str) -> Path:
    """A local dump path; downloads a URL into dumps/ first (reused if already there)."""
    if not source.startswith(("http://", "https://")):
        path = Path(source).expanduser()
        if not path.is_file():
            raise SnapshotError(f"no such dump file: {source}")
        return path
    DUMPS.mkdir(exist_ok=True)
    target = DUMPS / Path(urlsplit(source).path).name
    if target.is_file() and target.stat().st_size > 0:
        print(f"==> Using the copy already downloaded: {target.relative_to(ROOT)}")
        return target
    print(f"==> Downloading {source}")
    partial = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(source, timeout=60) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, length=1 << 20)
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise SnapshotError(f"download failed: {error}") from error
    partial.rename(target)
    print(f"    {target.stat().st_size / 1e6:.0f} MB -> {target.relative_to(ROOT)}")
    return target


def restore(
    source: str,
    force: bool = False,
    if_empty: bool = False,
    migrate: bool = True,
    no_terrain: bool = False,
) -> int:
    env = pg_env(database_url())
    connection = connect(env)
    print(f"==> Target: {describe(env)}")
    existing = non_empty_tables(connection)
    if existing:
        if if_empty:
            print(f"    The database already has data ({len(existing)} tables); not restoring.")
            return 0
        if not force:
            shown = ", ".join(existing[:6]) + (" ..." if len(existing) > 6 else "")
            raise SnapshotError(
                f"refusing to restore: the database already has data in {len(existing)} "
                f"tables ({shown}).\nA restore replaces every table, including accounts. "
                "FIX: make restore DUMP=<url> FORCE=1  (or --force) if that is what you want."
            )
    dump = fetch(source)
    print(f"==> {ensure_postgis(connection)}")
    with tempfile.TemporaryDirectory(dir=DUMPS if DUMPS.exists() else None) as work:
        workdir = Path(work)
        linked = workdir / "restore.dump"
        try:
            os.link(dump, linked)
        except OSError:
            shutil.copy(dump, linked)
        tools = Tools(env, workdir)
        print(f"==> pg_restore ({tools.mode})")
        (workdir / "restore.list").write_text(
            "\n".join(restore_list(toc_lines(tools, "restore.dump"), no_terrain)) + "\n"
        )
        dropped = drop_public_tables(connection)
        if dropped:
            print(f"    dropped {dropped} existing tables")
        tools.run(
            [
                "pg_restore",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--use-list=restore.list",
                f"--dbname={env['PGDATABASE']}",
                "restore.dump",
            ]
        )
    print(summary(connection))
    connection.close()
    if migrate:
        print("==> Migrations")
        subprocess.run(
            [sys.executable, str(ROOT / "backend" / "manage.py"), "migrate", "--no-input"],
            env={**os.environ, "DATABASE_URL": database_url()},
            check=True,
        )
    print(
        "Restored. Snapshots hold no accounts: make one with the app's Create account, or "
        "backend/manage.py createsuperuser."
    )
    return 0


def dump(out: Path) -> int:
    env = pg_env(database_url())
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tools = Tools(env, out.parent)
    print(f"==> pg_dump {describe(env)} ({tools.mode})")
    args = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--schema=public"]
    args += [f"--exclude-table-data={pattern}" for pattern in PERSONAL_TABLES]
    tools.run([*args, f"--file={out.name}"])
    try:
        check(out, tools)
    except SnapshotError:
        out.unlink(missing_ok=True)
        raise
    print(f"Dump written: {out} ({out.stat().st_size / 1e6:.0f} MB)")
    return 0


def check(path: Path, tools: Tools | None = None) -> int:
    path = path.resolve()
    tools = tools or Tools({}, path.parent)  # reading a file needs no connection
    lines = toc_lines(tools, path.name)
    tables = data_tables(lines)
    leaked = [table for table in tables if personal(table)]
    print(f"{path.name}: rows for {len(tables)} tables")
    for table in tables:
        print(f"  {table}")
    if leaked:
        raise SnapshotError(f"the dump holds personal data: {', '.join(leaked)}")
    print("No personal tables have data.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_restore = sub.add_parser("restore", help="restore a dump (path or URL) into DATABASE_URL")
    p_restore.add_argument("source")
    p_restore.add_argument("--force", action="store_true", help="replace a database with data")
    p_restore.add_argument("--if-empty", action="store_true", help="skip quietly if it has data")
    p_restore.add_argument("--no-migrate", action="store_true", help="skip migrate afterwards")
    p_restore.add_argument(
        "--no-terrain",
        action="store_true",
        help="restore the terrain tables empty (about 0.6 GB less; for a 1 GB free tier)",
    )
    p_dump = sub.add_parser("dump", help="dump DATABASE_URL, without personal data")
    p_dump.add_argument("--out", type=Path, default=DUMPS / f"campsite-{date.today()}.dump")
    p_check = sub.add_parser("check", help="list a dump's tables; fail on personal data")
    p_check.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "restore":
            return restore(
                args.source, args.force, args.if_empty, not args.no_migrate, args.no_terrain
            )
        if args.command == "dump":
            return dump(args.out)
        return check(args.path)
    except SnapshotError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
