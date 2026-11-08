"""
The production deployment's configuration (TM05-161): render.yaml, backend/Dockerfile, the
CI deploy job and scripts/restore_production.sh. Nothing here talks to Render or to any
hosted database.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
RESTORE = ROOT / "scripts" / "restore_production.sh"


def render():
    return yaml.safe_load((ROOT / "render.yaml").read_text())


def service(name):
    return next(s for s in render()["services"] if s["name"] == name)


def env_vars(name):
    return {var["key"]: var for var in service(name)["envVars"]}


# --- render.yaml -----------------------------------------------------------------------------


@pytest.mark.unit
def test_render_yaml_commits_no_secret_values():
    secret_words = ("SECRET", "PASSWORD", "TOKEN", "KEY", "DATABASE_URL", "DSN")
    for svc in render()["services"]:
        for var in svc.get("envVars", []):
            if any(word in var["key"] for word in secret_words):
                assert "value" not in var, f"{svc['name']}: {var['key']} has a committed value"
                assert (
                    var.get("generateValue") or var.get("fromDatabase") or var.get("sync") is False
                )


@pytest.mark.unit
def test_the_database_is_a_paid_postgres_16():
    (db,) = render()["databases"]
    assert db["plan"] != "free"  # free databases expire after 30 days and have no backups
    assert db["postgresMajorVersion"] == "16"
    assert db["diskSizeGB"] >= 2  # the snapshot restores to about 1.2 GB


@pytest.mark.unit
def test_the_api_migrates_before_deploy_and_is_production_configured():
    api = service("campsite-api")
    assert api["plan"] != "free"  # pre-deploy commands need a paid instance
    assert api["preDeployCommand"] == "python manage.py migrate --no-input"
    assert api["healthCheckPath"] == "/api/health/"
    assert api["dockerfilePath"] == "./backend/Dockerfile"
    env = env_vars("campsite-api")
    assert env["DEBUG"]["value"] == "False"
    assert env["BEHIND_TLS_PROXY"]["value"] == "True"
    assert env["MIGRATE_ON_START"]["value"] == "False"
    assert env["SECRET_KEY"] == {"key": "SECRET_KEY", "generateValue": True}
    assert env["DATABASE_URL"]["fromDatabase"]["name"] == "campsite-db"
    for origin in ("CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS"):
        assert env[origin]["sync"] is False


@pytest.mark.unit
def test_the_frontend_is_a_static_spa_build():
    web = service("campsite-web")
    assert web["runtime"] == "static"
    assert web["buildCommand"] == "npm ci && npm run build"
    assert web["staticPublishPath"] == "dist"
    assert {"type": "rewrite", "source": "/*", "destination": "/index.html"} in web["routes"]
    env = env_vars("campsite-web")
    assert env["NODE_VERSION"]["value"] == (ROOT / ".nvmrc").read_text().strip()
    for name in ("VITE_API_BASE_URL", "VITE_MAP_STYLE_URL"):
        assert env[name]["sync"] is False


@pytest.mark.unit
def test_only_ci_deploys():
    # Render's own auto-deploy is off on both services; the CI deploy job triggers them.
    for svc in render()["services"]:
        assert svc["autoDeployTrigger"] == "off"
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    deploy = ci["jobs"]["deploy"]
    assert sorted(deploy["needs"]) == ["frontend", "quality"]
    assert "refs/heads/main" in deploy["if"] and "push" in deploy["if"]
    assert deploy["env"]["API_HOOK"] == "${{ secrets.RENDER_DEPLOY_HOOK }}"
    steps = {step["name"]: step for step in deploy["steps"]}
    # Each hook is called only when its secret exists, so the job is a no-op without them.
    assert steps["Deploy the backend (campsite-api)"]["if"] == "env.API_HOOK != ''"
    assert steps["Deploy the frontend (campsite-web)"]["if"] == "env.WEB_HOOK != ''"


# --- backend/Dockerfile ----------------------------------------------------------------------


@pytest.mark.unit
def test_the_image_serves_gunicorn_with_static_files_and_a_health_check():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text()
    assert "collectstatic --no-input" in dockerfile  # served by whitenoise
    assert "exec gunicorn config.wsgi:application" in dockerfile
    assert '"${MIGRATE_ON_START:-True}" = "True"' in dockerfile
    assert "HEALTHCHECK" in dockerfile and "/api/health/" in dockerfile
    assert "USER app" in dockerfile


# --- scripts/restore_production.sh -----------------------------------------------------------


def restore(*args, stdin=""):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COV_CORE_", "COVERAGE"))}
    env["PYTHON"] = sys.executable
    return subprocess.run(
        ["bash", str(RESTORE), *args], input=stdin, capture_output=True, text=True, env=env
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "args, code, message",
    [
        ((), 2, "usage"),
        (("postgres://u:p@h/db",), 2, "usage"),
        (("mysql://u:p@h/db", "x.dump"), 2, "postgres:// URL"),
        (("postgres://u:p@h/db", "x.dump", "--bogus"), 2, "usage"),
        (("postgres:///db", "x.dump"), 2, "names no host"),
    ],
)
def test_restore_production_rejects_bad_arguments(args, code, message):
    result = restore(*args)
    assert result.returncode == code
    assert message in result.stderr


@pytest.mark.unit
def test_restore_production_asks_for_the_host_and_stops_on_a_mismatch():
    result = restore(
        "postgres://u:p@prod.example.com/db?sslmode=require", "x.dump", stdin="wrong\n"
    )
    assert result.returncode == 1
    assert "into the database on host: prod.example.com" in result.stdout
    assert "nothing was changed" in result.stdout
    assert "p@" not in result.stdout  # the password is never echoed


@pytest.mark.django_db(transaction=True)
def test_restore_production_refuses_a_database_with_data():
    from django.db import connection

    from geodata.models import IngestRun

    IngestRun.objects.create(source="osm", region="adirondacks", started_at="2026-11-08T00:00Z")
    db = connection.settings_dict
    url = f"postgis://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db['PORT']}/{db['NAME']}"
    result = restore(url, "no-such.dump", "--yes")
    assert result.returncode == 1
    assert "refusing to restore" in result.stderr and "geodata_ingestrun" in result.stderr
