"""
The phone dev setup (TM05-103): the LAN origin is trusted for CORS and CSRF in development
only. Settings are read once at import, so each case imports them in a fresh interpreter.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
PRINT = (
    "import json; from config import settings; "
    "print(json.dumps([settings.CORS_ALLOWED_ORIGINS, settings.CSRF_TRUSTED_ORIGINS]))"
)


def settings_with(**env):
    result = subprocess.run(
        [sys.executable, "-c", PRINT],
        cwd=BACKEND,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_lan_origin_is_trusted_in_development():
    cors, csrf = settings_with(DEBUG="True", DEV_LAN_ORIGIN="https://192.168.1.20:5173")
    assert "https://192.168.1.20:5173" in cors
    assert csrf == ["https://192.168.1.20:5173"]


def test_the_lan_origin_is_ignored_when_debug_is_off():
    cors, csrf = settings_with(
        DEBUG="False", DEV_LAN_ORIGIN="https://192.168.1.20:5173", SECRET_KEY="test-only-key"
    )
    assert "https://192.168.1.20:5173" not in cors
    assert csrf == []


def test_nothing_changes_without_it():
    _, csrf = settings_with(DEBUG="True", DEV_LAN_ORIGIN="")
    assert csrf == []


def test_make_dev_phone_runs_vite_in_phone_mode():
    makefile = (BACKEND.parent / "Makefile").read_text()
    target = makefile[makefile.index("dev-phone:") :]
    target = target[: target.index("\n\n")]
    assert "PHONE=1" in target and "VITE_API_BASE_URL=" in target
    assert "DEV_LAN_ORIGIN=https://$(LAN_IP):5173" in target
    config = (BACKEND.parent / "frontend" / "vite.config.ts").read_text()
    assert "basicSsl()" in config and "process.env.PHONE === '1'" in config
