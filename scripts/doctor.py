"""
CampSite environment check (TM05-67). Run with `make doctor`.

Prints one line per check:
    PASS <check>: <what was found>
    FAIL <check>: <what is wrong>
         FIX: <the command or edit that fixes it>
    WARN <check>: <worth knowing, not blocking>
and exits non-zero if anything failed. Written to be read by people and by Claude Code:
every FAIL carries a concrete FIX.

Runs under the project virtualenv when it exists (the Makefile uses .venv/bin/python),
and degrades to the checks it can do with the standard library when it does not.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db_path  # noqa: E402 -- scripts/db_path.py, the TM05-160 path detection
import snapshot  # noqa: E402 -- scripts/snapshot.py, for its client-tools check

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
# What each development path needs in .env. POSTGRES_* only configure the local Compose
# database (path B); the dev container and a hosted database only need DATABASE_URL.
REQUIRED_ENV = [
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "DATABASE_URL",
    "CORS_ALLOWED_ORIGINS",
]
REQUIRED_ENV_NO_COMPOSE = ["DATABASE_URL", "CORS_ALLOWED_ORIGINS"]
# Variables the process environment may set over .env (the dev container sets several).
OVERRIDABLE = {"DATABASE_URL", "DEBUG", "SECRET_KEY", "CORS_ALLOWED_ORIGINS"}
PATH_NAMES = {
    "devcontainer": "A, the dev container (database: its db service)",
    "docker": "B, local Docker (database: the Compose container)",
    "hosted": "C, a hosted PostGIS (database: DATABASE_URL)",
}

failures = 0


def report(status: str, check: str, detail: str, fix: str | None = None) -> None:
    global failures
    if status == "FAIL":
        failures += 1
    print(f"{status} {check}: {detail}")
    if fix:
        print(f"     FIX: {fix}")


def run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(command, 127, "", str(error))


def read_env() -> dict[str, str]:
    env_file = ROOT / ".env"
    values: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


# --- checks ------------------------------------------------------------------------------


def check_python() -> None:
    version = platform.python_version()
    in_venv = sys.prefix != sys.base_prefix
    if version.startswith("3.12."):
        report("PASS", "python", f"{version} ({'.venv' if in_venv else sys.executable})")
    else:
        report(
            "FAIL",
            "python",
            f"{version} -- CampSite needs 3.12 (3.13/3.14 fail to build some wheels here)",
            "install Python 3.12 (macOS: brew install python@3.12; Ubuntu/WSL: "
            "sudo apt install python3.12 python3.12-venv), then: rm -rf .venv && make setup",
        )
    if not in_venv:
        report("WARN", "python", "not running inside .venv", "make setup (creates .venv)")


def check_requirements() -> None:
    """Every pin in requirements.txt is installed at that version in the running Python."""
    if sys.prefix == sys.base_prefix:
        return  # check_python already warns; the system Python is not ours to judge
    from importlib.metadata import PackageNotFoundError, version

    stale = []
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" not in line:
            continue
        name, wanted = (part.strip() for part in line.split("==", 1))
        try:
            installed = version(name)
        except PackageNotFoundError:
            stale.append(f"{name} missing")
            continue
        if installed != wanted:
            stale.append(f"{name} {installed} (want {wanted})")
    if stale:
        report(
            "FAIL",
            "requirements",
            ", ".join(stale),
            ".venv/bin/pip install -r requirements.txt",
        )
    else:
        report("PASS", "requirements", "requirements.txt pins all installed")


def check_node() -> None:
    wanted = (ROOT / ".nvmrc").read_text().strip() if (ROOT / ".nvmrc").exists() else "22"
    result = run(["node", "--version"])
    if result.returncode != 0:
        report("FAIL", "node", "node not found", f"install Node {wanted} (nvm install {wanted})")
        return
    version = result.stdout.strip().lstrip("v")
    major = int(version.split(".")[0])
    if major >= int(wanted):
        report("PASS", "node", f"v{version} (CI uses {wanted})")
    else:
        report("FAIL", "node", f"v{version}, need {wanted}+", f"nvm install {wanted} && nvm use")
    if not (ROOT / "frontend" / "node_modules").exists():
        report("FAIL", "node", "frontend/node_modules missing", "cd frontend && npm ci")


def check_env(env: dict[str, str], path: str = "docker") -> None:
    if not (ROOT / ".env").exists():
        report("FAIL", ".env", "missing", "make setup (copies .env.example to .env)")
        return
    required = REQUIRED_ENV if path == "docker" else REQUIRED_ENV_NO_COMPOSE
    missing = [key for key in required if not env.get(key)]
    if missing:
        report(
            "FAIL",
            ".env",
            f"unset: {', '.join(missing)}",
            "copy the missing lines from .env.example into .env",
        )
    else:
        report("PASS", ".env", f"all {len(required)} required variables set")
    url = env.get("DATABASE_URL", "")
    if path == "docker":
        check_compose_env(env, url)
    elif path == "hosted":
        check_hosted_env(url)
    if ":5173" not in env.get("CORS_ALLOWED_ORIGINS", ""):
        report(
            "FAIL",
            ".env",
            "CORS_ALLOWED_ORIGINS does not include port 5173 (Vite)",
            "CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173",
        )
    # Since TM05-113, settings.py only falls back to the dev key when DEBUG=True; with DEBUG
    # unset (off) and no SECRET_KEY, Django refuses to start.
    if not env.get("SECRET_KEY"):
        if env.get("DEBUG") == "True":
            report("WARN", ".env", "SECRET_KEY unset -- DEBUG=True, so a dev-only key is used")
        else:
            report(
                "FAIL",
                ".env",
                "SECRET_KEY unset and DEBUG is not True -- Django will refuse to start",
                "add DEBUG=True and SECRET_KEY=<any long random string> to .env "
                "(see .env.example)",
            )
    if not env.get("RIDB_API_KEY"):
        report("WARN", ".env", "RIDB_API_KEY empty -- fine; only the optional ridb ingest needs it")


def check_compose_env(env: dict[str, str], url: str) -> None:
    """Path B: DATABASE_URL must reach the Compose container docker-compose.yml creates."""
    port = env.get("POSTGRES_PORT", "5432")
    if url and f":{port}/" not in url:
        report(
            "FAIL",
            ".env",
            f"DATABASE_URL does not use POSTGRES_PORT={port}",
            f"set the port in DATABASE_URL to {port}",
        )
    password = env.get("POSTGRES_PASSWORD", "")
    if url and password and f":{password}@" not in url:
        report(
            "FAIL",
            ".env",
            "DATABASE_URL password differs from POSTGRES_PASSWORD",
            "make the password in DATABASE_URL match POSTGRES_PASSWORD",
        )


def check_hosted_env(url: str) -> None:
    """Path C: a hosted database is reached over the internet, so it needs TLS."""
    if "sslmode=" not in url:
        report(
            "WARN",
            ".env",
            "DATABASE_URL has no sslmode -- hosted providers require TLS",
            "append ?sslmode=require to DATABASE_URL",
        )


def check_database_reachable(env: dict[str, str], path: str) -> bool:
    """Paths A and C: a TCP connection to the database host. (Path B uses check_docker.)"""
    url = env.get("DATABASE_URL", "")
    try:
        target = urlsplit(url)
        host, port = target.hostname or "", target.port or 5432
    except ValueError:
        host, port = "", 5432
    if not host:
        report("FAIL", "database host", "DATABASE_URL names no host", "see .env.example")
        return False
    if path == "devcontainer":
        fix = (
            "the dev container's db service is not running. VS Code: Dev Containers: Rebuild "
            "Container. Codespaces: Codespaces: Rebuild Container. (On the host: docker compose "
            "-f .devcontainer/docker-compose.yml up -d db)"
        )
    else:
        fix = (
            "check the host and port in DATABASE_URL against the provider's dashboard, that the "
            "database is not paused or deleted, and that the provider allows your IP address"
        )
    try:
        with socket.create_connection((host, port), timeout=5):
            pass
    except OSError as error:
        report("FAIL", "database host", f"cannot reach {host}:{port} ({error})", fix)
        return False
    report("PASS", "database host", f"{host}:{port} reachable")
    return True


def check_restore_tools(path: str) -> None:
    """make restore and make dump need PostgreSQL 16 client tools, or Docker to run them."""
    major = snapshot.tools_major("pg_restore")
    if (major or 0) >= snapshot.MIN_TOOLS_MAJOR:
        report("PASS", "pg tools", f"pg_restore {major} (for make restore / make dump)")
    elif shutil.which("docker"):
        report("PASS", "pg tools", "pg_restore runs in Docker (postgis/postgis:16-3.4)")
    else:
        fix = (
            "rebuild the dev container (its image has postgresql-client-16)"
            if path == "devcontainer"
            else "macOS: brew install libpq && brew link --force libpq; Ubuntu: "
            "sudo apt install postgresql-client-16 (apt.postgresql.org); or install Docker"
        )
        found = f"pg_restore {major} is too old (the snapshot is a PG16 dump)" if major else ""
        report(
            "WARN", "pg tools", found or "no pg_restore 16+ and no Docker: make restore fails", fix
        )


def check_docker(env: dict[str, str]) -> bool:
    name = env.get("DB_CONTAINER_NAME") or "campsite_db"
    if not shutil.which("docker"):
        report(
            "FAIL",
            "docker",
            "docker not installed",
            "install Docker Desktop (macOS/Windows) or docker-ce + compose plugin (Linux)",
        )
        return False
    if run(["docker", "info"]).returncode != 0:
        report("FAIL", "docker", "Docker is not running", "start Docker Desktop, then make setup")
        return False
    report("PASS", "docker", "daemon running")
    health = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", name])
    status = health.stdout.strip()
    if health.returncode != 0:
        report(
            "FAIL", "database container", f"{name} does not exist", "docker compose up -d --wait"
        )
        return False
    if status != "healthy":
        report(
            "FAIL",
            "database container",
            f"{name} is {status or 'not running'}",
            f"docker compose up -d --wait  (logs: docker logs {name})",
        )
        return False
    report("PASS", "database container", f"{name} healthy")
    return True


def check_ports(env: dict[str, str], path: str = "docker") -> None:
    name = env.get("DB_CONTAINER_NAME") or "campsite_db"
    ports = [(8000, "backend"), (5173, "frontend")]
    db_port, mapped = None, ""
    if path == "docker":  # elsewhere the database is not on this machine's ports
        db_port = int(env.get("POSTGRES_PORT") or 5432)
        mapped = run(["docker", "port", name, "5432"]).stdout
        ports.insert(0, (db_port, "database"))
    for port, ours in ports:
        owner = port_owner(port)
        if owner is None:
            if port == db_port:
                report(
                    "FAIL",
                    f"port {port}",
                    "free, but the database should be listening",
                    "docker compose up -d --wait",
                )
            else:
                report("PASS", f"port {port}", f"free for the {ours}")
            continue
        if port == db_port and f":{port}" in mapped:
            report("PASS", f"port {port}", f"in use by {name}")
        elif (
            port in (8000, 5173)
            and str(ROOT) in owner
            and ("runserver" in owner or "vite" in owner)
        ):
            report("PASS", f"port {port}", f"in use by this checkout's {ours}")
        else:
            fix = (
                "set POSTGRES_PORT to a free port (e.g. 5434) in .env, use it in DATABASE_URL, "
                "then docker compose up -d --wait"
                if port == db_port
                else f"stop the process using {port} ({owner})"
            )
            report("FAIL", f"port {port}", f"in use by something else: {owner}", fix)


def port_owner(port: int) -> str | None:
    """Who holds a TCP port, as 'command [in <cwd>]'; None if the port is free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) != 0:
            return None
    if shutil.which("lsof"):
        pids = run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"]).stdout.split()
    elif shutil.which("ss"):
        pids = re.findall(r"pid=(\d+)", run(["ss", "-ltnp", f"sport = :{port}"]).stdout)
    else:
        pids = []
    owners = []
    for pid in dict.fromkeys(pids):
        command = run(["ps", "-o", "command=", "-p", pid]).stdout.strip()
        if command:
            owners.append(f"{command} [in {process_cwd(pid)}]")
    # Docker Desktop's port proxy often runs as another user, invisible to lsof.
    return " | ".join(owners) or "unknown process (maybe Docker)"


def process_cwd(pid: str) -> str:
    try:
        return os.readlink(f"/proc/{pid}/cwd")  # Linux / WSL
    except OSError:
        pass
    for line in run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"]).stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return "?"


def check_django(env: dict[str, str], db_up: bool) -> None:
    if sys.prefix == sys.base_prefix:
        report("WARN", "django", "skipped: not running in .venv", "make setup, then make doctor")
        return
    os.environ.update({k: v for k, v in env.items() if k not in os.environ})
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        import django

        django.setup()
        from django.contrib.gis.gdal import gdal_version
        from django.contrib.gis.geos import geos_version

        report("PASS", "gdal", f"GDAL {gdal_version().decode()}, GEOS {geos_version().decode()}")
    except Exception as error:  # noqa: BLE001 -- any import failure is the finding
        text = str(error)
        if "GDAL" in text or "GEOS" in text:
            fix = (
                "macOS: brew install gdal geos, and set GDAL_LIBRARY_PATH / GEOS_LIBRARY_PATH in "
                ".env (see .env.example). Linux/WSL: sudo apt install gdal-bin libgdal-dev "
                "libgeos-dev, and leave both paths unset."
            )
        else:
            fix = "read the error above; check .env against .env.example"
        report("FAIL", "django", f"{type(error).__name__}: {text[:200]}", fix)
        return
    if not db_up:
        report("FAIL", "database connection", "skipped: container not healthy", "see above")
        return
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT postgis_lib_version()")
            postgis = cursor.fetchone()[0]
        report("PASS", "database connection", f"PostGIS {postgis} via DATABASE_URL")
    except Exception as error:  # noqa: BLE001
        text = str(error)
        if "postgis_lib_version" in text:
            fix = (
                "PostGIS is not enabled in this database. make restore enables it; or run "
                "CREATE EXTENSION postgis; as the database's admin role"
            )
        else:
            fix = "check DATABASE_URL credentials and port (path B: match POSTGRES_* in .env)"
        report("FAIL", "database connection", f"{type(error).__name__}: {text[:200]}", fix)
        return

    from django.core.management import call_command

    try:
        call_command("migrate", check=True, plan=False, verbosity=0)
        report("PASS", "migrations", "all applied")
    except SystemExit:
        report(
            "FAIL",
            "migrations",
            "unapplied migrations",
            ".venv/bin/python backend/manage.py migrate",
        )
    except Exception as error:  # noqa: BLE001
        report("FAIL", "migrations", str(error)[:200], ".venv/bin/python backend/manage.py migrate")
        return

    check_data()


def check_data() -> None:
    from django.apps import apps
    from django.db.utils import ProgrammingError

    tables = [
        ("geodata", "Campsite"),
        ("geodata", "Trail"),
        ("geodata", "TrailRoute"),
        ("geodata", "WaterFeature"),
        ("geodata", "PublicLand"),
        ("enrichment", "CampsiteFacts"),
        ("analysis", "AnalysisResult"),
        ("geodata", "Landmark"),
        ("routing", "TrailEdge"),
        ("terrain", "TerrainFacts"),
    ]
    counts = {}
    try:
        for app, model in tables:
            counts[model] = apps.get_model(app, model).objects.count()
    except ProgrammingError as error:
        report("FAIL", "data", str(error)[:200], ".venv/bin/python backend/manage.py migrate")
        return
    summary = ", ".join(f"{model} {count:,}" for model, count in counts.items())
    core = ["Campsite", "Trail", "WaterFeature", "PublicLand"]
    if all(counts[model] == 0 for model in core):
        report(
            "FAIL",
            "data",
            f"database is empty ({summary})",
            "make restore DUMP=<url>  (fast; `make restore` prints the latest snapshot URL)  "
            "or  make data  (full rebuild)",
        )
    elif any(counts[model] == 0 for model in core):
        empty = [model for model in core if counts[model] == 0]
        report(
            "WARN",
            "data",
            f"some layers empty: {', '.join(empty)} ({summary})",
            "make data STEPS=<step>  for the missing source(s)",
        )
    else:
        report("PASS", "data", summary)


def main() -> int:
    print(f"CampSite doctor -- {platform.system()} {platform.machine()}, repo {ROOT}\n")
    env = read_env()
    # The process environment wins over .env, as it does for Django (the dev container sets
    # DATABASE_URL), so the checks look at what Django will actually use.
    env.update({key: os.environ[key] for key in OVERRIDABLE if os.environ.get(key)})
    path = db_path.detect(env)
    print(f"Path: {PATH_NAMES[path]} -- docs/setup.md\n")
    check_python()
    check_requirements()
    check_node()
    check_env(env, path)
    if path == "docker":
        db_up = check_docker(env)
    else:
        db_up = check_database_reachable(env, path)
    check_restore_tools(path)
    check_ports(env, path)
    check_django(env, db_up)
    print()
    if failures:
        print(f"{failures} check(s) FAILED. Apply each FIX above, then run make doctor again.")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
