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

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
REQUIRED_ENV = [
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "DATABASE_URL",
    "CORS_ALLOWED_ORIGINS",
]

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


def check_node() -> None:
    wanted = (ROOT / ".nvmrc").read_text().strip() if (ROOT / ".nvmrc").exists() else "20"
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


def check_env(env: dict[str, str]) -> None:
    if not (ROOT / ".env").exists():
        report("FAIL", ".env", "missing", "make setup (copies .env.example to .env)")
        return
    missing = [key for key in REQUIRED_ENV if not env.get(key)]
    if missing:
        report(
            "FAIL",
            ".env",
            f"unset: {', '.join(missing)}",
            "copy the missing lines from .env.example into .env",
        )
    else:
        report("PASS", ".env", f"all {len(REQUIRED_ENV)} required variables set")
    url = env.get("DATABASE_URL", "")
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
    if ":5173" not in env.get("CORS_ALLOWED_ORIGINS", ""):
        report(
            "FAIL",
            ".env",
            "CORS_ALLOWED_ORIGINS does not include port 5173 (Vite)",
            "CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173",
        )
    if not env.get("SECRET_KEY"):
        report("WARN", ".env", "SECRET_KEY unset -- settings.py falls back to a dev-only key")
    if not env.get("RIDB_API_KEY"):
        report("WARN", ".env", "RIDB_API_KEY empty -- fine; only the optional ridb ingest needs it")


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


def check_ports(env: dict[str, str]) -> None:
    name = env.get("DB_CONTAINER_NAME") or "campsite_db"
    db_port = int(env.get("POSTGRES_PORT") or 5432)
    mapped = run(["docker", "port", name, "5432"]).stdout
    for port, ours in ((db_port, "database"), (8000, "backend"), (5173, "frontend")):
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
        report(
            "FAIL",
            "database connection",
            f"{type(error).__name__}: {str(error)[:200]}",
            "check DATABASE_URL credentials and port match POSTGRES_* in .env",
        )
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
    check_python()
    check_node()
    check_env(env)
    db_up = check_docker(env)
    check_ports(env)
    check_django(env, db_up)
    print()
    if failures:
        print(f"{failures} check(s) FAILED. Apply each FIX above, then run make doctor again.")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
