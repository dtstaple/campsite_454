"""
Which of the three development paths this checkout uses (TM05-160, docs/setup.md).

    python3 scripts/db_path.py      # prints: devcontainer, docker or hosted

- hosted        DATABASE_URL points at a server that is not this machine or the dev
                container's `db` service: a hosted PostGIS (path C).
- devcontainer  running inside the dev container (.devcontainer/ sets CAMPSITE_DEVCONTAINER=1),
                with the database in its `db` service (path A).
- docker        everything else: the database in Docker Compose on this machine (path B).

`make setup` starts Docker Compose only on the docker path, and `make doctor` picks its
database checks from it. Standard library only, so it runs before the virtualenv exists.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}
DEVCONTAINER_DB_HOST = "db"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def in_devcontainer(environ: dict[str, str]) -> bool:
    return environ.get("CAMPSITE_DEVCONTAINER") == "1"


def database_host(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def detect(env: dict[str, str], environ: dict[str, str] | None = None) -> str:
    """The path in use, from .env values (`env`) and the process environment."""
    environ = os.environ if environ is None else environ
    url = environ.get("DATABASE_URL") or env.get("DATABASE_URL", "")
    host = database_host(url)
    if host not in LOCAL_HOSTS and host != DEVCONTAINER_DB_HOST:
        return "hosted"
    if in_devcontainer(environ):
        return "devcontainer"
    return "docker"


def main() -> int:
    print(detect(read_env_file(ROOT / ".env")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
