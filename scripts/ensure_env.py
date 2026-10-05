"""
Create .env from .env.example if it is missing, and fill in what can be detected (TM05-67).

    python3 scripts/ensure_env.py

Never overwrites an existing .env. On macOS with Homebrew GDAL/GEOS installed, it fills
GDAL_LIBRARY_PATH and GEOS_LIBRARY_PATH (Django 5.1 cannot find GDAL 3.9+ by itself);
elsewhere it leaves them unset, which means "search the system default paths".
Standard library only, so it runs before the virtualenv exists.
"""

from __future__ import annotations

import platform
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"


def brew_prefix(formula: str) -> str | None:
    if not shutil.which("brew"):
        return None
    result = subprocess.run(
        ["brew", "--prefix", formula], capture_output=True, text=True, check=False
    )
    prefix = result.stdout.strip()
    return prefix if result.returncode == 0 and Path(prefix).exists() else None


def main() -> int:
    if ENV.exists():
        print(f"OK   .env already exists ({ENV}); leaving it untouched.")
        return 0
    text = EXAMPLE.read_text()
    text = text.replace(
        "SECRET_KEY=change-me-locally", f"SECRET_KEY={secrets.token_urlsafe(40)}", 1
    )
    if platform.system() == "Darwin":
        gdal, geos = brew_prefix("gdal"), brew_prefix("geos")
        if gdal and geos:
            text = text.replace(
                "# GDAL_LIBRARY_PATH=\n# GEOS_LIBRARY_PATH=\n",
                f"GDAL_LIBRARY_PATH={gdal}/lib/libgdal.dylib\n"
                f"GEOS_LIBRARY_PATH={geos}/lib/libgeos_c.dylib\n",
                1,
            )
            print(f"OK   GDAL/GEOS paths set from Homebrew ({gdal}, {geos}).")
        else:
            print("WARN Homebrew gdal/geos not found. FIX: brew install gdal geos, then rerun.")
    ENV.write_text(text)
    print(f"OK   created .env from .env.example ({ENV}). Review it; never commit it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
