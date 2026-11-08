#!/usr/bin/env bash
# Runs once when the dev container is created (TM05-160): make setup, then the latest team
# snapshot. The restore is skipped when the database already holds data, so rebuilding the
# container keeps whatever is in the database volume.
set -euo pipefail
cd "$(dirname "$0")/.."

# The named volumes for .venv and node_modules are created root-owned.
sudo chown vscode:vscode .venv frontend/node_modules

start=$(date +%s)
make setup
url=$(make -s snapshot-url)
.venv/bin/python scripts/snapshot.py restore "$url" --if-empty
echo
echo "Dev container ready in $(( $(date +%s) - start )) s. Next: make doctor, then make dev,"
echo "and open the forwarded port 5173."
