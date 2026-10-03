# Setup

This is the one setup guide. The README, `docs/onboarding.md` and `CLAUDE.md` all point
here. Run every command from the repo root unless a step says otherwise.

The short version, once the prerequisites are installed:

```
git clone https://github.com/dtstaple/campsite_454.git
cd campsite_454
make setup
make restore DUMP=<dump URL from the team channel>
make doctor
make dev
```

Then open http://localhost:5173.

## 1. Prerequisites

The versions match CI: Python **3.12** (`.python-version`) and Node **20 or newer**
(`.nvmrc`).

### macOS

1. Install [Homebrew](https://brew.sh), then the tools:

   ```
   brew install python@3.12 node@20 gdal geos
   ```

   If you already manage Node with nvm, run `nvm install && nvm use` instead of
   `node@20`.

2. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.

`make` and `git` come with the Xcode Command Line Tools: `xcode-select --install`.

### Windows: use WSL2

The project runs inside Ubuntu on WSL2. It is not supported natively on Windows: the
Makefile, the shell scripts and GDAL all assume a Unix environment.

1. In an **administrator** PowerShell, run `wsl --install -d Ubuntu-24.04`, reboot, and
   create your Linux user when Ubuntu opens.
2. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/), then turn on
   **Settings → Resources → WSL integration → Ubuntu-24.04**. `docker` now works inside
   Ubuntu, and you do not install Docker inside WSL separately.
3. In the Ubuntu terminal, follow the Linux steps below.
4. Clone into your Linux home (`~/campsite_454`), **not** `/mnt/c/...`. Builds and file
   watching are very slow across the Windows filesystem.
5. In VS Code, install the **WSL** extension, then run `code .` from the Ubuntu terminal.
   VS Code and Claude Code then run inside Linux.

`localhost:5173` and `localhost:8000` in a Windows browser reach the servers running in
WSL.

### Linux (Ubuntu 24.04, including WSL)

```
sudo apt update
sudo apt install -y git make curl python3.12 python3.12-venv \
    gdal-bin libgdal-dev libgeos-dev
```

Install Node 20 with nvm:

```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
```

Reopen the terminal, then run `nvm install 20`.

Docker on native Linux: install Docker Engine and the compose plugin from
[docs.docker.com/engine/install/ubuntu](https://docs.docker.com/engine/install/ubuntu/), then
`sudo usermod -aG docker $USER` and log out and back in.

On Ubuntu 22.04, `python3.12` is not in the default repositories. Add it with
`sudo add-apt-repository ppa:deadsnakes/ppa` first.

## 2. `make setup`

```
make setup
```

It is safe to re-run. It does the following:

1. Creates `.venv` with Python 3.12 and installs `requirements.txt`. It refuses an
   existing `.venv` that is on the wrong Python, and tells you how to fix it.
2. Runs `npm ci` in `frontend/`.
3. Creates `.env` from `.env.example`, **only if `.env` does not exist**, with a random
   `SECRET_KEY`. On macOS it also fills in the Homebrew GDAL/GEOS paths (see
   [Troubleshooting](#gdal)).
4. Starts PostgreSQL 16 + PostGIS 3.4 in Docker (`docker compose up -d --wait`). The
   container is `campsite_db`, and its data lives in a named volume that survives restarts.
5. Applies the migrations.

`.env` holds every variable the backend and Docker read. Each one is explained in
`.env.example`. `RIDB_API_KEY` is optional: only the `ridb` ingest uses it, and it skips
cleanly without one.

## 3. Get data

A fresh database is empty. Choose one of three ways to fill it:

| Path | Command | Time | What you get |
|---|---|---|---|
| **Restore a dump** (recommended) | `make restore DUMP=<url-or-path>` | ~15 s + downloading ~110 MB | Everything a teammate has: every region ingested so far, routes, profiles, enrichment |
| Full rebuild | `make data` | ~30 min to 3+ h (estimate; see below) | The Adirondacks rebuilt from the live sources |
| Sample | `.venv/bin/python backend/manage.py seed` | seconds | One 7 × 7 km patch, the Essex Chain Lakes; enough for UI work |

### Restore a dump

```
make restore DUMP=https://github.com/dtstaple/campsite_454/releases/download/<tag>/<file>.dump
```

`DUMP` can be a URL or a local path. Restoring **replaces** the data in your local
database.

Dumps never contain accounts, tokens, sessions or saved campsites, so make yourself a login
afterwards (see [section 5](#5-log-in)).

To publish a dump for the team:

```
make dump
```

This writes `dumps/campsite-<date>.dump`; `dumps/` is gitignored. Then upload it as a
GitHub Release asset:

```
gh release create data-<date> dumps/campsite-<date>.dump \
    --title "Data snapshot <date>" --notes "make restore DUMP=<asset URL>"
```

### Full rebuild

```
make data
```

This rebuilds the Adirondacks from the live sources. It runs every ingest, in this order:

1. padus
2. nhd-flowlines
3. nhd-waterbodies
4. osm-trails
5. osm-campsites
6. ridb (skipped without a key)
7. osm-routes

Then it precomputes 3DEP elevation profiles for every named route (`build_route_profiles`)
and enriches the campsites (`enrich_campsites`). Each step is timed, and a summary table
prints at the end.

- **Run part of it:** `make data STEPS=padus,osm-routes`.
- **Another region:** `make data REGION=white-mountains-nh`. The regions are listed in
  `backend/pipeline/regions.yml`.
- **Re-running is safe:** ingests upsert, and profiles and enrichment are cached.

**How long it takes (estimate, 2026-10-03).** The ingests take about 7 minutes in total:

| Step | Measured |
|---|---|
| padus | 19 s |
| nhd-flowlines | 4 min |
| nhd-waterbodies | 1 min |
| osm-trails | 1.5 min |
| osm-campsites | 15 s |
| osm-routes | 5–20 s |

Enrichment takes about 2.5 minutes cold.

The route profiles dominate. They cover 270 named routes and 3,450 km of trail, and 3DEP's
speed varies a lot: from ~0.33 s/km on a good day (about 20 min) to 3.2 s/km on
2026-10-03, when it was returning 502s (about 3 h). Profiles are also computed on first
view in the app, so you can stop after `enrich` and lose nothing but a wait in the trail
panel. A step that fails part-way is safe to re-run, because finished work is cached.

The upstream services (Overpass, NHD, PAD-US, 3DEP) are public and occasionally slow or
down. When a step fails, the run stops and prints the command that re-runs just that step.
The details of each source are in `docs/pipeline.md`.

### Sample data

```
.venv/bin/python backend/manage.py seed
```

It prints one line with a count for every layer:

```
Seeded sample dataset: 6 public lands, 25 trails, 134 water features, 15 campsites.
```

All four numbers should be non-zero. If any is `0`, the fixture is broken, not your setup.

The sample is one small box around the Essex Chain Lakes (`-74.29, 43.825` to
`-74.20, 43.885`), in the lower half of the map, south of centre. **Everywhere else is empty,
and that is expected.**

`.venv/bin/python backend/manage.py reset_db` wipes the database back to the sample. Add
`--noinput` to skip the confirmation.

## 4. Check and run

```
make doctor
```

`make doctor` prints `PASS`, `FAIL` or `WARN` for each of these:

- Python and Node versions
- `.env` and its required variables
- Docker, and the `campsite_db` container's health
- the database connection
- GDAL loading inside Django
- migrations
- row counts for each data table
- ports 5432, 8000 and 5173: free, or used by our own processes

Every `FAIL` comes with a `FIX:` line giving the command to run. Paste the output into
Claude Code if the fix is not obvious. The command exits non-zero while anything fails.

```
make dev
```

`make dev` runs the backend on http://localhost:8000 and the frontend on
http://localhost:5173 together, and Ctrl-C stops both. To run them in separate terminals,
use `make backend` and `make frontend`.

Open **http://localhost:5173** (see [Troubleshooting](#the-basemap-is-blank) for why
`localhost`).

## 5. Log in

- **The app:** click **Create account** (top right) on http://localhost:5173. The account lives
  only in your local database.
- **Django admin:** create a superuser, then sign in at http://localhost:8000/admin/:

  ```
  .venv/bin/python backend/manage.py createsuperuser
  ```

  The admin is the quickest way to inspect ingested rows and `IngestRun` provenance.

`make restore` removes local accounts, so repeat both steps after a restore.

## 6. Checking the data makes sense

The unit suite (`pytest`) tests code against fixtures and never looks at your database.
`pytest -m data` does. It runs read-only against whatever `DATABASE_URL` points at, and both
a plain `pytest` and CI skip it. It checks that:

- at least one region holds all four layers (public land, trails, water, campsites)
- at least 75% of each region's campsites have water and a trail within 1 km
- every feature touches the bbox of the region it was ingested for (1 km tolerance)
- no more than 1% of trails are sidewalks, crossings, golf paths or non-path highways

The thresholds and the reasoning behind them are at the top of
`tests/data_checks/test_data_coherence.py`.

## 7. Before you push

```
source .venv/bin/activate
ruff check . && ruff format --check . && pytest
cd frontend && npm run lint && npm run build
```

CI runs the same checks. Branch, commit and Jira rules are in `CLAUDE.md` and
`docs/CONTRIBUTING.md`.

## 8. Troubleshooting

### GDAL

The error is `Could not find the GDAL library` or `Could not find the GEOS library`.

Django 5.1 looks for GDAL by name and only knows versions 3.0–3.8, so it never finds the
current Homebrew GDAL (3.9+). The fix is to give Django the paths in `.env`:

```
# Apple Silicon
GDAL_LIBRARY_PATH=/opt/homebrew/opt/gdal/lib/libgdal.dylib
GEOS_LIBRARY_PATH=/opt/homebrew/opt/geos/lib/libgeos_c.dylib
# Intel Mac: the same, with /usr/local in place of /opt/homebrew
```

`make setup` writes these automatically if `brew install gdal geos` ran first. The
`opt/` paths are symlinks that follow Homebrew upgrades.

**On Linux/WSL, leave both variables unset.** Ubuntu's GDAL is on the default library path
and is a version Django knows. If you do need to set them, the paths are
`/usr/lib/x86_64-linux-gnu/libgdal.so` and `/usr/lib/x86_64-linux-gnu/libgeos_c.so`
(`aarch64-linux-gnu` on ARM).

### `pip install` fails building a wheel

You are on Python 3.13 or 3.14. Some pinned dependencies have no wheels for those versions
yet, so pip tries to compile them and fails. Use 3.12:

```
rm -rf .venv
make setup
```

`make setup` finds `python3.12` by name. Check that `python3.12 --version` works.

### Port already in use

`make doctor` names the process holding the port.

- **5432:** usually a Homebrew or system PostgreSQL. The symptom is that Django reports
  `role "campsite" does not exist` even though Docker is running. Either stop that
  PostgreSQL, or set `POSTGRES_PORT=5434` in `.env` and use the same port in
  `DATABASE_URL`. Then run `docker compose up -d --wait`.
- **8000 or 5173:** an old `runserver` or Vite is still running. Stop it, or let `make dev`
  report it.

### The basemap is blank

Check these three things:

- **The URL.** Stadia's terms allow keyless use of the basemap from `localhost` only, so
  develop on http://localhost:5173. Any other domain needs to be registered with Stadia
  (free for non-commercial use) or to use a style URL with an API key, set as
  `VITE_MAP_STYLE_URL` in `frontend/.env`; the variable is listed in `.env.example`.
  - What was observed: in a check on 2026-10-03, Stadia served tiles to any page that
    sent a `Referer` and returned `401` without one.
  - Even so, don't rely on other hosts working without a key.
- **`maplibre-gl.css`.** It is imported **exactly once**, in `frontend/src/main.tsx`,
  before `index.css` and `App.css`.
  - If a component imports it as well, the stylesheet order can flip.
  - When it does, MapLibre's `.maplibregl-map { position: relative }` beats our `.map`,
    and the map container collapses to zero height: a black void with the panels
    floating over it.
  - The comment in `main.tsx` explains this.
- **`optimizeDeps`.** `frontend/vite.config.ts` excludes `maplibre-gl` from Vite's
  dependency pre-bundling on purpose.
  - Keep that exclude.
  - If the map works in `npm run build && npm run preview` but not in `npm run dev`,
    check the exclude, then restart Vite with `npm run dev -- --force` to clear the
    pre-bundle cache.

### The map loads but there is no data, or login fails with a CORS error

`CORS_ALLOWED_ORIGINS` in `.env` must include the frontend's origin, port **5173**:

```
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

The fallback in `settings.py` is port 3000, which is from before Vite, so an `.env` without
this line blocks every request. After changing `.env`, restart the backend.

### Docker container unhealthy, or `make setup` hangs at "Database container"

Check that Docker Desktop is running, then look at the container's log:

```
docker logs campsite_db
```

If you changed `POSTGRES_PASSWORD` after the volume was created, the old password is still
in effect. Reset the database, which **deletes local data**:

```
docker compose down -v
make setup
```

### `npm test` fails with `ERR_UNKNOWN_FILE_EXTENSION ".ts"`

The frontend unit tests use Node's built-in TypeScript type stripping, which needs Node
**22.6+**. CI pins Node 20 for lint and build. To run `npm test` locally:

```
nvm install 22
nvm use 22
```

### Running a second copy side by side

Create the second checkout's `.env` **before** `make setup`, so it never touches the first
database:

```
python3 scripts/ensure_env.py
```

Then give it its own Compose project, container and port in that `.env`:

```
COMPOSE_PROJECT_NAME=campsite_b
DB_CONTAINER_NAME=campsite_db_b
POSTGRES_PORT=5442
```

Use the same port in `DATABASE_URL`, then run `make setup`. The two databases and their
volumes never touch.

### Pointing at a different database

Pointing the app at another database, including a hosted one, only means changing
`DATABASE_URL`. See `docs/deployment.md`.
