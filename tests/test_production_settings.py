"""
Production settings (TM05-113): DEBUG is off by default, a missing SECRET_KEY stops Django
when DEBUG is off, and HTTPS hardening is switched on only behind a TLS proxy. Settings are
read once at import, so each case imports them in a fresh interpreter.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
PRINT = (
    "import json; from config import settings as s; print(json.dumps([s.DEBUG, s.ALLOWED_HOSTS,"
    " s.CORS_ALLOWED_ORIGINS, s.CSRF_TRUSTED_ORIGINS, getattr(s, 'SECURE_SSL_REDIRECT', False),"
    " getattr(s, 'SECURE_PROXY_SSL_HEADER', None)]))"
)
CLEARED = (
    "DEBUG",
    "SECRET_KEY",
    "ALLOWED_HOSTS",
    "CORS_ALLOWED_ORIGINS",
    "CSRF_TRUSTED_ORIGINS",
    "BEHIND_TLS_PROXY",
    "RENDER_EXTERNAL_HOSTNAME",
    "DEV_LAN_ORIGIN",
)


def run_settings(**env):
    # Without pytest-cov's variables (see test_dev_phone.py). The repo's .env is loaded by
    # settings.py but never overrides a variable that is already set, so blank values here
    # stand in for "unset".
    base = {k: v for k, v in os.environ.items() if not k.startswith(("COV_CORE_", "COVERAGE"))}
    base.update(dict.fromkeys(CLEARED, ""))
    return subprocess.run(
        [sys.executable, "-c", PRINT],
        cwd=BACKEND,
        env={**base, **env},
        capture_output=True,
        text=True,
    )


def test_debug_off_without_secret_key_refuses_to_start():
    result = run_settings()
    assert result.returncode != 0
    assert "SECRET_KEY is not set" in result.stderr


def test_debug_is_off_by_default():
    result = run_settings(SECRET_KEY="test-only-key")
    debug, *_ = json.loads(result.stdout)
    assert debug is False


def test_debug_on_keeps_the_dev_key_fallback():
    result = run_settings(DEBUG="True")
    assert result.returncode == 0, result.stderr


def test_production_lists_come_from_the_environment():
    result = run_settings(
        SECRET_KEY="test-only-key",
        ALLOWED_HOSTS="api.example.com, ",
        RENDER_EXTERNAL_HOSTNAME="campsite-api.onrender.com",
        CORS_ALLOWED_ORIGINS="https://campsite.example.com",
        CSRF_TRUSTED_ORIGINS="https://campsite.example.com",
    )
    _, hosts, cors, csrf, *_ = json.loads(result.stdout)
    assert hosts == ["api.example.com", "campsite-api.onrender.com"]
    assert cors == ["https://campsite.example.com"]
    assert csrf == ["https://campsite.example.com"]


def test_https_hardening_only_behind_a_tls_proxy():
    plain = json.loads(run_settings(SECRET_KEY="test-only-key").stdout)
    proxied = json.loads(run_settings(SECRET_KEY="test-only-key", BEHIND_TLS_PROXY="True").stdout)
    assert plain[4:] == [False, None]
    assert proxied[4:] == [True, ["HTTP_X_FORWARDED_PROTO", "https"]]
