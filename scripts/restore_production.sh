#!/usr/bin/env bash
# Load the team snapshot into the production database (TM05-161). docs/deployment.md,
# "Production data".
#
#   scripts/restore_production.sh <DATABASE_URL> <snapshot URL or path> [--force] [--yes]
#
# Run from a checkout with `make setup` done (it uses .venv and scripts/snapshot.py). Use the
# database's EXTERNAL URL from the Render dashboard, with ?sslmode=require. Quote it: it
# contains characters the shell would otherwise read. Never paste it into chat, Jira or git.
#
# What it does, in order:
#   1. refuses a database that already has data, unless --force (a restore replaces every
#      table: production accounts, saved campsites and plans are lost);
#   2. asks you to type the database's host name, unless --yes;
#   3. creates the PostGIS extension if it is missing;
#   4. restores the snapshot (pg_restore 16+, or the postgis/postgis:16-3.4 image via Docker);
#   5. runs Django's migrations against it, and prints row counts.
# Steps 1 and 3-5 are scripts/snapshot.py restore, the same code `make restore` uses.
set -euo pipefail

usage() {
  echo "usage: scripts/restore_production.sh <DATABASE_URL> <snapshot URL or path> [--force] [--yes]" >&2
  exit 2
}

[[ $# -ge 2 ]] || usage
url="$1"
snapshot="$2"
shift 2
force=""
yes=""
for arg in "$@"; do
  case "$arg" in
    --force) force="--force" ;;
    --yes) yes=1 ;;
    *) usage ;;
  esac
done

root="$(cd "$(dirname "$0")/.." && pwd)"
# PYTHON: another interpreter with requirements.txt installed (CI uses its own).
python="${PYTHON:-$root/.venv/bin/python}"
[[ -x "$python" ]] || { echo "FAIL $python not found. FIX: make setup" >&2; exit 1; }

case "$url" in
  postgres://* | postgresql://* | postgis://*) ;;
  *) echo "FAIL the first argument must be a postgres:// URL" >&2; exit 2 ;;
esac

# The host, without credentials, to confirm against.
host="$("$python" -c 'import sys; from urllib.parse import urlsplit; print(urlsplit(sys.argv[1]).hostname or "")' "$url")"
case "$host" in
  "" ) echo "FAIL the URL names no host" >&2; exit 2 ;;
esac
if [[ "$url" != *sslmode=* && "$host" != localhost && "$host" != 127.0.0.1 ]]; then
  echo "WARN no sslmode in the URL; hosted databases need ?sslmode=require" >&2
fi

if [[ -z "$yes" ]]; then
  echo "About to restore $snapshot"
  echo "into the database on host: $host"
  read -r -p "Type the host name to continue: " typed
  [[ "$typed" == "$host" ]] || { echo "Host did not match; nothing was changed."; exit 1; }
fi

# DEBUG=True only lets manage.py migrate start without the production SECRET_KEY; nothing
# here serves requests. DATABASE_URL reaches the tools as PG* variables, never as argv.
export DATABASE_URL="$url"
export DEBUG=True
"$python" "$root/scripts/snapshot.py" restore "$snapshot" $force
echo
echo "Next: run the smoke test against the live URLs (docs/deployment.md, \"Checking a deploy\")."
