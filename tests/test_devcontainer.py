"""
The portable dev environment (TM05-160): path detection (scripts/db_path.py), the dev
container's wiring, and the dev-only Codespaces origins in settings.py.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
DEVCONTAINER = ROOT / ".devcontainer"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- which path ------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "dot_env_url, environ, expected",
    [
        ("postgis://campsite:pw@localhost:5432/campsite", {}, "docker"),
        ("postgis://campsite:pw@127.0.0.1:5434/campsite", {}, "docker"),
        (
            "postgis://campsite:pw@localhost:5432/campsite",
            {"CAMPSITE_DEVCONTAINER": "1"},
            "devcontainer",
        ),
        (
            "postgis://campsite:pw@localhost:5432/campsite",
            {"CAMPSITE_DEVCONTAINER": "1", "DATABASE_URL": "postgis://c:p@db:5432/campsite"},
            "devcontainer",
        ),
        ("postgres://u:p@ep-x.neon.tech/campsite?sslmode=require", {}, "hosted"),
        # A hosted URL wins even inside the dev container.
        ("postgres://u:p@db.supabase.co/postgres", {"CAMPSITE_DEVCONTAINER": "1"}, "hosted"),
        # The process environment wins over .env, as python-dotenv does for Django.
        (
            "postgis://c:p@localhost:5432/c",
            {"DATABASE_URL": "postgres://u:p@h.example/db"},
            "hosted",
        ),
        ("", {}, "docker"),
        ("not a url [", {}, "docker"),
    ],
)
def test_detect_the_path(dot_env_url, environ, expected):
    db_path = load_script("db_path")
    assert db_path.detect({"DATABASE_URL": dot_env_url}, environ) == expected


@pytest.mark.unit
def test_db_path_reads_dot_env(tmp_path, monkeypatch, capsys):
    db_path = load_script("db_path")
    (tmp_path / ".env").write_text("# c\nDATABASE_URL=postgres://u:p@far.example/db\n")
    monkeypatch.setattr(db_path, "ROOT", tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CAMPSITE_DEVCONTAINER", raising=False)
    assert db_path.main() == 0
    assert capsys.readouterr().out.strip() == "hosted"
    assert db_path.read_env_file(tmp_path / "missing") == {}


# --- the dev container -----------------------------------------------------------------------


def jsonc(path):
    """devcontainer.json allows // comments; strip whole-line ones."""
    return json.loads(
        "\n".join(
            line for line in path.read_text().splitlines() if not line.strip().startswith("//")
        )
    )


@pytest.mark.unit
def test_devcontainer_config():
    config = jsonc(DEVCONTAINER / "devcontainer.json")
    assert config["forwardPorts"] == [5173, 8000]
    assert config["service"] == "app"
    assert config["postCreateCommand"] == "bash .devcontainer/post-create.sh"
    node = config["features"]["ghcr.io/devcontainers/features/node:1"]["version"]
    assert node == (ROOT / ".nvmrc").read_text().strip()  # the same Node as CI

    compose = (DEVCONTAINER / "docker-compose.yml").read_text()
    assert "image: postgis/postgis:16-3.4" in compose  # the same image as CI
    assert 'CAMPSITE_DEVCONTAINER: "1"' in compose
    assert "@db:5432/campsite" in compose
    # The database is never published on the host, so it cannot clash with campsite_db.
    db = compose[compose.index("  db:") :]
    assert "ports:" not in db
    # A host's .venv and node_modules never reach the Linux container.
    assert "venv:/workspaces/campsite_454/.venv" in compose
    assert "node_modules:/workspaces/campsite_454/frontend/node_modules" in compose

    dockerfile = (DEVCONTAINER / "Dockerfile").read_text()
    assert "python:1-3.12-bookworm" in dockerfile
    for package in ("gdal-bin", "libgeos-dev", "postgresql-client-16"):
        assert package in dockerfile


@pytest.mark.unit
def test_post_create_sets_up_then_restores_only_into_an_empty_database():
    script = (DEVCONTAINER / "post-create.sh").read_text()
    assert script.index("make setup") < script.index("snapshot.py restore")
    assert "--if-empty" in script and "make -s snapshot-url" in script


@pytest.mark.unit
def test_vite_proxies_the_api_in_the_devcontainer():
    config = (ROOT / "frontend" / "vite.config.ts").read_text()
    assert "process.env.CAMPSITE_DEVCONTAINER === '1'" in config
    assert "allowedHosts" in config and "proxy: apiProxy" in config
    assert "process.env.VITE_API_BASE_URL = ''" in config
    assert "exclude: ['maplibre-gl']" in config  # CLAUDE.md: keep it


@pytest.mark.unit
def test_makefile_wiring():
    makefile = (ROOT / "Makefile").read_text()
    assert "scripts/db_path.py" in makefile
    assert re.search(r"restore:.*?scripts/snapshot.py restore .*?--force", makefile, re.S)
    assert "scripts/snapshot.py dump" in makefile
    assert re.search(r"snapshot-url:\n\t@echo \$\(SNAPSHOT_URL\)", makefile)


@pytest.mark.unit
def test_ensure_env_points_at_the_db_service_in_the_devcontainer(tmp_path, monkeypatch):
    ensure_env = load_script("ensure_env")
    example = tmp_path / ".env.example"
    example.write_text(
        "DATABASE_URL=postgis://campsite:change-me-locally@localhost:5432/campsite\n"
        "SECRET_KEY=change-me-locally\n# GDAL_LIBRARY_PATH=\n# GEOS_LIBRARY_PATH=\n"
    )
    monkeypatch.setattr(ensure_env, "ENV", tmp_path / ".env")
    monkeypatch.setattr(ensure_env, "EXAMPLE", example)
    monkeypatch.setenv("CAMPSITE_DEVCONTAINER", "1")
    monkeypatch.setattr(ensure_env.platform, "system", lambda: "Darwin")  # never Homebrew here
    ensure_env.main()
    text = (tmp_path / ".env").read_text()
    assert "@db:5432/campsite" in text and "localhost" not in text
    assert "# GDAL_LIBRARY_PATH=\n" in text


# --- Codespaces origins ----------------------------------------------------------------------

PRINT = (
    "import json; from config import settings as s; "
    "print(json.dumps([s.ALLOWED_HOSTS, s.CORS_ALLOWED_ORIGINS, s.CSRF_TRUSTED_ORIGINS]))"
)


def settings_with(**env):
    # Without pytest-cov's variables (see test_dev_phone.py).
    base = {k: v for k, v in os.environ.items() if not k.startswith(("COV_CORE_", "COVERAGE"))}
    base.update(dict.fromkeys(("CSRF_TRUSTED_ORIGINS", "DEV_LAN_ORIGIN"), ""))
    result = subprocess.run(
        [sys.executable, "-c", PRINT],
        cwd=BACKEND,
        env={**base, **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


CODESPACE = {
    "CODESPACE_NAME": "fuzzy-space-x7",
    "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN": "app.github.dev",
}


def test_codespaces_origins_are_trusted_in_development():
    hosts, cors, csrf = settings_with(DEBUG="True", **CODESPACE)
    assert "fuzzy-space-x7-8000.app.github.dev" in hosts
    for port in (5173, 8000):
        assert f"https://fuzzy-space-x7-{port}.app.github.dev" in cors
        assert f"https://fuzzy-space-x7-{port}.app.github.dev" in csrf


def test_codespaces_origins_are_ignored_when_debug_is_off():
    hosts, cors, csrf = settings_with(DEBUG="False", SECRET_KEY="test-only-key", **CODESPACE)
    assert not any("github.dev" in value for value in hosts + cors + csrf)
