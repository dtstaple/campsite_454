# Setup

This is the one setup guide. The README, `docs/onboarding.md` and `CLAUDE.md` all point
here. Run every command from the repo root unless a step says otherwise.

## Choose a path (TM05-160)

There are three ways to get a working CampSite with real data. They run the same code, use
the same `make` commands, and load the same snapshot. They differ in where the tools and
the database live.

| Path | What you install | Where the database is | Clone to running app with data |
|---|---|---|---|
| **A. Dev container** (GitHub Codespaces, or VS Code locally) | Nothing (Codespaces), or Docker + VS Code | A PostGIS container next to the app container | about 3 min on a Mac (measured); a Codespace not yet measured |
| **B. Local Docker** | Python 3.12, Node 22, GDAL, Docker | `campsite_db` in Docker on your machine | about 2 min (116 s measured) |
| **C. Hosted dev database** | Python 3.12, Node 22, GDAL; **no Docker** | Your own branch of a hosted PostGIS (Neon) | not measured yet (needs the hosted database) |

How the times were measured is under [Measured setup times](#measured-setup-times).

- **New to the project, or Docker Desktop keeps failing you:** path A in a Codespace. It
  needs only a browser.
- **Day-to-day development on your own machine:** path B. It is the fastest once set up
  and works offline.
- **A machine where Docker is not an option** (a locked-down laptop, a low-memory
  machine): path C.

`make doctor` tells you which path it detected, and checks that path:

```
Path: A, the dev container (database: its db service) -- docs/setup.md
```

The data is the same everywhere: the team snapshot
[dev-data-2026-11-10](https://github.com/dtstaple/campsite_454/releases/tag/dev-data-2026-11-10) (483 MB download, about 1.36 GB restored).
It holds every ingested layer for the Adirondacks and the White Mountains, enrichment,
the routing graph (Adirondacks), terrain facts and zones for both regions, and peaks and
trailheads. It holds **no user data**. What is in it is in [data-status.md](data-status.md).

## Path A: dev container (Codespaces or VS Code)

Everything is defined in `.devcontainer/`:

- an app container with Python 3.12, Node 22, GDAL/GEOS and the PostgreSQL 16 client
  tools, and
- a `db` service on `postgis/postgis:16-3.4`, the same image as CI.

When the container is created, `.devcontainer/post-create.sh` runs `make setup` and then
restores the latest snapshot. Nothing else is needed.

### In GitHub Codespaces

1. On https://github.com/dtstaple/campsite_454, click **Code → Codespaces → Create
   codespace on main**. Choose a **4-core** machine if asked (`hostRequirements` asks for
   4 cores and 8 GB).
2. Wait for the post-create step to finish. The terminal ends with
   `Dev container ready in N s`. The first creation builds the image, installs the Python and Node
   packages, and downloads and restores the snapshot: about 3 minutes on a Mac once the base
   image is pulled (see [Measured setup times](#measured-setup-times)). A Codespace also pulls
   the 2.3 GB base image the first time.
3. In the terminal, run `make doctor`, then `make dev`.
4. Open the **Ports** tab and click the globe next to **5173 CampSite (frontend)**.
   Codespaces usually opens it for you.

How it works in a Codespace:

- The page is served at `https://<codespace>-5173.app.github.dev`. Vite **proxies
  `/api`** to Django inside the container, so the page and the API share an origin and no
  CORS is involved. The ports stay **private** (only you, signed in to GitHub, can open
  them), and that still works because the API calls never leave the page's origin.
- The Django admin is on the forwarded port 8000. In development only (`DEBUG=True`),
  `settings.py` trusts the Codespace's own forwarded hosts for the admin's login form.
- **The basemap.** Stadia serves its keyless basemap to `localhost` only, by its terms.
  On an `app.github.dev` address the basemap may be blank or refused. The data layers
  still draw. To get the basemap, either forward the port to your own machine with
  `gh codespace ports forward 5173:5173` and open http://localhost:5173, or set
  `VITE_MAP_STYLE_URL` in `frontend/.env` to a style URL with your own Stadia key.
- **Quota.** GitHub Free gives 120 core-hours of Codespaces a month, which is about 30
  hours on a 4-core machine. Stop the codespace when you are done (it also stops itself
  after 30 idle minutes), and delete old ones under https://github.com/codespaces.

### In VS Code on your own machine

1. Install Docker Desktop and VS Code with the **Dev Containers** extension.
2. Open the repo folder, then run **Dev Containers: Reopen in Container** from the
   command palette.
3. As above: wait for `Dev container ready`, then `make doctor` and `make dev`, and open
   http://localhost:5173.

The dev container keeps to itself:

- Its database is a separate Compose project (`campsite-devcontainer`) with its own volume,
  and is **not published** on your machine's ports, so it never clashes with a local
  `campsite_db` on 5432.
- `.venv` and `frontend/node_modules` inside the container are separate Docker volumes.
  Your macOS or Windows copies are neither used nor changed.
- The container's environment sets `DATABASE_URL` to the `db` service and clears the
  Homebrew GDAL paths. Those win over the values in your `.env`, which is shared with the
  host, so the same `.env` works on both sides.

Rebuilding the container (**Dev Containers: Rebuild Container**) keeps the database
volume. The post-create step then sees a database with data and skips the restore. To
start from a fresh snapshot, run `make restore DUMP=$(make -s snapshot-url) FORCE=1`.

The same works without VS Code, with the Dev Containers CLI:

```
npx @devcontainers/cli up --workspace-folder .
npx @devcontainers/cli exec --workspace-folder . make doctor
```

## Path B: local Docker

### Prerequisites

The versions match CI: Python **3.12** (`.python-version`) and Node **22** (22.18 or newer)
(`.nvmrc`).

#### macOS

1. Install [Homebrew](https://brew.sh), then the tools:

   ```
   brew install python@3.12 node@22 gdal geos
   ```

   If you already manage Node with nvm, run `nvm install && nvm use` instead of
   `node@22`.

2. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.

`make` and `git` come with the Xcode Command Line Tools: `xcode-select --install`.

#### Windows: use WSL2

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

#### Linux (Ubuntu 24.04, including WSL)

```
sudo apt update
sudo apt install -y git make curl python3.12 python3.12-venv \
    gdal-bin libgdal-dev libgeos-dev
```

Install Node 22 with nvm:

```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
```

Reopen the terminal, then run `nvm install 22`.

Docker on native Linux: install Docker Engine and the compose plugin from
[docs.docker.com/engine/install/ubuntu](https://docs.docker.com/engine/install/ubuntu/), then
`sudo usermod -aG docker $USER` and log out and back in.

On Ubuntu 22.04, `python3.12` is not in the default repositories. Add it with
`sudo add-apt-repository ppa:deadsnakes/ppa` first.

### Then

```
git clone https://github.com/dtstaple/campsite_454.git
cd campsite_454
make setup
make restore DUMP=$(make -s snapshot-url)
make doctor
make dev
```

Then open http://localhost:5173. `make setup` is explained [below](#make-setup).

## Path C: a hosted dev database (no Docker)

The code is unchanged; only `DATABASE_URL` points somewhere else. Install the same tools as
path B (Python 3.12, Node 22, GDAL/GEOS), but **not Docker**. You also need the PostgreSQL
16 client tools for the restore: `brew install libpq && brew link --force libpq` on macOS,
or `sudo apt install postgresql-client-16` from [apt.postgresql.org](https://wiki.postgresql.org/wiki/Apt)
on Ubuntu/WSL. (`make doctor` checks them, as `pg tools`.)

### Size first

The full snapshot is about 1.16 GB once restored. The provider must allow that much
storage, with headroom for indexes and the cache tables the app writes as you use it.
**That is more than Neon's Free plan (1 GB per project).** Two ways round it:

- **Free, without terrain.** Restore with `NO_TERRAIN=1`. Every terrain table is restored
  empty (the zones alone are about 0.6 GB), and the restored database is then
  506 MB (measured 2026-11-08). The app works as it does in any region `make
  terrain` hasn't reached: no terrain facts in campsite panels, no terrain zone overlays,
  and Find campsites says "Water pooling risk not checked: no terrain data here yet". It is
  all of the terrain tables or none, because the app decides whether terrain was checked
  from the terrain runs; leaving only the zones out would make that check pass everywhere.
- **Everything, on a paid plan.** Neon's paid plans have no 1 GB cap; check the current
  pricing at https://neon.com/pricing before choosing.

### Recommended: Neon, one branch per developer

[Neon](https://neon.com) is hosted PostgreSQL with PostGIS and **branches**: a branch is
an instant copy-on-write copy of the database, so each developer gets their own writable
copy of the data, and storage that is the same as on the parent branch is not counted
twice.

One person (the team's data owner) does this once:

1. Sign up at https://console.neon.tech and create a project named `campsite-dev`,
   **PostgreSQL 16**, in the region nearest the team (US East).
2. In the project's **SQL Editor**, run `CREATE EXTENSION postgis;`. (The restore also
   tries this, but only the owner role is certain to be allowed.)
3. Copy the connection string of the `main` branch (**Connect**, with "Pooled connection"
   **off**: pg_restore needs a direct connection). It looks like
   `postgresql://<user>:<password>@ep-<name>.<region>.aws.neon.tech/neondb?sslmode=require`.
4. Restore the snapshot into `main`, from a checkout with `make setup` done:

   ```
   DATABASE_URL='postgresql://...?sslmode=require' \
       make restore DUMP=$(make -s snapshot-url) NO_TERRAIN=1
   ```

   Leave out `NO_TERRAIN=1` on a paid plan.

5. Under **Branches**, create one branch per developer from `main`: `dev-davis`,
   `dev-bleron`, `dev-abdulrahman`, `dev-sahaj`. Then invite each teammate to the project
   (**Settings → Collaborators**) or send each one their branch's connection string
   privately (never in Jira, Slack channels or git).

Each developer then:

1. Puts their own branch's connection string in `.env` as `DATABASE_URL`, keeping
   `?sslmode=require`. Percent-encode special characters in the password (`@` becomes
   `%40`).
2. Runs `make setup`. It sees a hosted URL and starts no Docker container
   (`==> Database: the hosted path`), then migrates.
3. Runs `make doctor`, then `make dev`.

A branch already has the data, so there is nothing to restore. To reset your branch to
the team's data, use **Branches → your branch → Reset from parent** in the Neon console.
After a new team snapshot, the data owner restores it into `main` with `FORCE=1`, and
everyone resets their branch.

**Free plan limits (checked 2026-11-08; check the pricing page before relying on them).**
Neon's Free plan gives 1 GB of storage per project and 10 branches per project; writes
fail above 1 GB until space is freed. Compute suspends after 5 idle minutes and wakes on
the next connection, which adds a second or so to the first request.

**Other providers.** Any PostgreSQL 16 with PostGIS works the same way: one database per
developer instead of one branch. Supabase and Render both offer PostGIS. Render's free
database expires after 30 days, so it is not suited to a dev database.

**Hosted means slower.** Every API request makes a round trip to the provider. Map panning
and trail panels feel noticeably slower than on paths A and B. Use path C when you cannot
run Docker, not as the default.

### What `make restore` does on a hosted database

- It reads `DATABASE_URL` from the environment, else from `.env`, and passes `sslmode`
  and the other connection settings on to the PostgreSQL tools.
- It **refuses a database that already has data**, and names the tables, unless you add
  `FORCE=1`. A restore replaces every table, including accounts.
- It creates the PostGIS extension when it is missing, and explains what to do if the
  role is not allowed to.
- It restores, then runs Django's migrations, then prints row counts.

## make setup

```
make setup
```

It is safe to re-run. It does the following:

1. Creates `.venv` with Python 3.12 and installs `requirements.txt`. It refuses an
   existing `.venv` that is on the wrong Python, and tells you how to fix it.
2. Runs `npm ci` in `frontend/`.
3. Creates `.env` from `.env.example`, **only if `.env` does not exist**, with a random
   `SECRET_KEY`. On macOS it also fills in the Homebrew GDAL/GEOS paths (see
   [Troubleshooting](#gdal)); in the dev container it points `DATABASE_URL` at the `db`
   service.
4. **Path B only:** starts PostgreSQL 16 + PostGIS 3.4 in Docker
   (`docker compose up -d --wait`). The container is `campsite_db`, and its data lives in
   a named volume that survives restarts. On paths A and C it prints which path it
   detected and starts nothing.
5. Applies the migrations.

`.env` holds every variable the backend and Docker read. Each one is explained in
`.env.example`. `RIDB_API_KEY` is optional: only the `ridb` ingest uses it, and it skips
cleanly without one.

## Get data

A fresh database is empty. Choose one of three ways to fill it:

| Way | Command | Time | What you get |
|---|---|---|---|
| **Restore the snapshot** (recommended) | `make restore DUMP=$(make -s snapshot-url)` | 81 s including the 380 MB download (measured) | Everything: both regions, routes, profiles, enrichment, the routing graph, terrain, peaks and trailheads |
| Full rebuild | `make data` | ~30 min to 3+ h (see below) | The Adirondacks rebuilt from the live sources |
| Sample | `.venv/bin/python backend/manage.py seed` | seconds | One 7 × 7 km patch, the Essex Chain Lakes; enough for UI work |

### Restore the snapshot

```
make restore DUMP=$(make -s snapshot-url)
```

`make -s snapshot-url` prints the current snapshot's URL, which is `SNAPSHOT_URL` in the
`Makefile`:

```
https://github.com/dtstaple/campsite_454/releases/download/dev-data-2026-11-10/campsite-2026-11-10.dump
```

- `DUMP` can be a URL or a local path. A URL is downloaded into `dumps/` once and reused.
- It works on every path: it talks to whatever `DATABASE_URL` points at, using
  `pg_restore` 16+ if you have it and the `postgis/postgis:16-3.4` image through Docker if
  you don't.
- **It refuses a database that already has data**, because a restore replaces every table,
  your local accounts included. To replace it anyway: `make restore DUMP=... FORCE=1`.
- It creates PostGIS if it is missing, restores, runs the migrations, and prints the row
  counts of the main tables.

Snapshots never contain accounts, tokens, sessions, saved campsites, waypoints, trip
plans, hikes or saved trails, so make yourself a login afterwards (see
[Log in](#log-in)).

### Publishing a new snapshot

```
make dump
```

This writes `dumps/campsite-<date>.dump` (`dumps/` is gitignored) from whatever
`DATABASE_URL` points at. Every person's data is left out: the tables matching
`PERSONAL_TABLES` in `scripts/snapshot.py` (`auth_user*`, `authtoken_token`,
`accounts_*`, `planning_*`, `django_session`, `django_admin_log`) are dumped empty. The
dump is then checked, and deleted if any of them has rows. A test
(`tests/test_snapshot.py`) fails if a new model that points at a user is not covered by
those patterns. To check any dump: `.venv/bin/python scripts/snapshot.py check <file>`.

Then upload it as a GitHub Release asset:

```
gh release create dev-data-<date> dumps/campsite-<date>.dump \
    --title "Dev database snapshot <date>" \
    --notes "Public geodata only, no user accounts. Restore with: make restore DUMP=<asset URL>"
```

Then point `SNAPSHOT_URL` in the `Makefile` at the new asset, and update
[data-status.md](data-status.md). The dev container picks up the new URL by itself.

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
6. osm-landmarks (peaks and trailheads)
7. ridb (skipped without a key)
8. osm-routes

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

### Refresh one region: `make refresh` (TM05-91)

```
make refresh REGION=adirondacks
```

One command that brings a region's data up to date and reports what it loaded. `REGION`
is a name from `backend/pipeline/regions.yml` and defaults to `adirondacks`. It runs, in
order:

1. **Every ingest source**, the same list `manage.py ingest --list-sources` prints:
   padus, nhd-flowlines, nhd-waterbodies, osm-trails, osm-campsites, osm-landmarks, ridb
   (skipped without `RIDB_API_KEY`), osm-routes. A newly registered source is included
   automatically.
2. **Route profiles** (`build_route_profiles`).
3. **Enrichment** (`enrich_campsites`, then `enrich_routes`).

It **stops at the first step that fails**, exits non-zero, and names the steps it did not
run. Fix the cause and run it again: ingests upsert, and profiles and enrichment are
cached, so the finished steps are quick the second time.

It always ends with a per-step summary. `seconds` is the time the step took, and
`records` is the row count from the `IngestRun` rows that step wrote; steps that write no
`IngestRun` (profiles, enrichment) show `-`. The layout, with illustrative numbers:

```
step              result       seconds   records  notes
padus             ok              19.2     1,574  IngestRun: partial
osm-trails        ok              88.0    18,067  IngestRun: success
ridb              skipped          0.0         -  RIDB_API_KEY not set
route-profiles    ok             412.5         -
enrich            ok             150.3         -
total                            670.0    19,641
```

`partial` is normal for some sources; see `docs/pipeline.md`, section 4.

**`make refresh` or `make data`?** They run the same steps in the same order. Use
`make refresh` for a whole region when you want the record counts; use `make data
STEPS=...` to re-run chosen steps.

**How it was verified.** The order, stopping on failure, the summary and the RIDB skip are
covered by `tests/test_refresh_command.py`, which runs in CI against PostGIS with every
step stubbed. It has not yet been run end to end against the live sources: the local
database was down when it was written (2026-10-13).

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


## Check and run

```
make doctor
```

`make doctor` first prints the path it detected, then `PASS`, `FAIL` or `WARN` for each
check. The path comes from `scripts/db_path.py`:

- **A, dev container:** inside the dev container (it sets `CAMPSITE_DEVCONTAINER=1`), with
  `DATABASE_URL` on the `db` service.
- **C, hosted:** `DATABASE_URL` points at any host other than this machine or `db`.
- **B, local Docker:** everything else.

| Check | A | B | C |
|---|---|---|---|
| Python 3.12, the pinned requirements, Node 22, `node_modules` | ✓ | ✓ | ✓ |
| `.env` and its required variables | `DATABASE_URL`, CORS | also `POSTGRES_*`, and that `DATABASE_URL` matches them | also warns without `sslmode` |
| The database server | `db:5432` reachable | Docker running, `campsite_db` healthy | the host reachable |
| PostgreSQL 16 client tools, for `make restore`/`make dump` | ✓ | ✓ (Docker counts) | ✓ |
| Ports | 8000, 5173 | 5432, 8000, 5173 | 8000, 5173 |
| GDAL inside Django, the connection and PostGIS, migrations | ✓ | ✓ | ✓ |
| Row counts: campsites, trails, routes, water, land, facts, landmarks, graph edges, terrain facts | ✓ | ✓ | ✓ |

Every `FAIL` comes with a `FIX:` line giving the command or setting that fixes it for that
path; for example, a dev container whose `db` service is down is told to rebuild the
container, and a hosted database without PostGIS is told how to enable it. Paste the output
into Claude Code if the fix is not obvious. The command exits non-zero while anything
fails.

```
make dev
```

`make dev` runs the backend on http://localhost:8000 and the frontend on
http://localhost:5173 together, and Ctrl-C stops both. To run them in separate terminals,
use `make backend` and `make frontend`. In a Codespace, open the forwarded port 5173
instead (path A).

Open **http://localhost:5173** (see [Troubleshooting](#the-basemap-is-blank) for why
`localhost`).

### Before a demo: `make prewarm`

The first **Find campsites along this trail** on a trail samples terrain from USGS 3DEP,
and takes 15–35 s (docs/candidates.md). After that it is cached for 30 days, and comes
back in milliseconds. To make the first click in a demo instant, warm the trails you will
show beforehand:

```
make prewarm                                             # the four demo trails
make prewarm TRAILS="Van Hoevenberg,Phelps Trail"        # or your own, comma-separated
.venv/bin/python backend/manage.py prewarm_candidates "Deer Pond Trail" --within 1000
```

**What it warms.** For each trail it runs the campsite search for the panel's default
corridor (500 m; use `--within` for another), and computes the trail's elevation profile,
so opening the panel is instant too. It prints the time each took, and whether it was
computed now or already cached.

**How names are matched**, the same way the trail panel would open them:
1. **A named route**, by exact name. Otherwise the longest route whose name starts with
   it ("Van Hoevenberg" → Van Hoevenberg Trail), otherwise the longest that contains it.
2. **Otherwise, named trail ways** with exactly that name, opened as assembled trails. Ways
   of one name that don't connect are separate trails, and each is warmed: "Deer Pond
   Trail" is two.

An unknown name is reported, the rest are still warmed, and the command then exits with
an error. Run it with the backend's database up. Run it again any time: cached trails take
no time.

**Measured (2026-10-08):**

| Trail | First run | Second run |
|---|---|---|
| Van Hoevenberg → Van Hoevenberg Trail | already cached | 0.0 s |
| Phelps Trail | 34.9 s (5 potential spots) | 0.0 s |
| Deer Pond Trail (3.5 mi piece) | 8.7 s (5) | 0.0 s |
| Deer Pond Trail (0.5 mi piece) | 3.7 s, plus a 1.5 s profile (1) | 0.0 s |
| Cheney Pond-Irishtown | 9.4 s (8) | 0.0 s |
| **Total** | **59.4 s** | **0.6 s** |

Times vary with 3DEP. A 502 from it is retried automatically. If it still fails, that
trail says "unavailable"; run `make prewarm` again later.

### Testing on a phone (iPhone or Android)

Location (the GPS dot, **Follow me**, "mi X.X along" a trail) only works over **HTTPS**.
The one exception is `localhost`, and a phone can't reach your laptop's localhost. To try
it on a real phone:

1. Put the phone and the computer on the **same Wi-Fi**.
2. Run **`make dev-phone`**. It prints the address to open, for example
   `https://192.168.1.20:5173/discover`.
   - If it can't find the LAN address, give it yourself:
     `make dev-phone LAN_IP=192.168.1.20`. On macOS the address is
     `ipconfig getifaddr en0`.
3. Open that address in **Safari** on the iPhone.
   - Safari warns that the connection isn't private, because the certificate is your
     computer's own throwaway self-signed one.
   - Tap **Show Details → visit this website**, then confirm. This happens once per
     certificate.
4. When the map asks for your location, tap **Allow**. Then:
   - **Location** (bottom left) shows the GPS dot and accuracy circle.
   - **Follow me** keeps the map on you. Dragging the map turns it off.
5. To install it: **Share → Add to Home Screen**. It opens full-screen with the CampSite
   icon. It has no offline support.

**What `make dev-phone` does:**
- Django runs on `127.0.0.1:8000` as usual. It is not exposed to the network.
- Vite serves the frontend over HTTPS on all interfaces (`PHONE=1`, with
  `@vitejs/plugin-basic-ssl`), and **proxies `/api`** to Django.
  `VITE_API_BASE_URL` is empty, so the page calls `/api/...` on its own origin. The phone
  then needs no CORS and hits no mixed-content block.
- `DEV_LAN_ORIGIN=https://<lan-ip>:5173` tells `settings.py` to trust that origin for
  CORS and CSRF. It does so **only while `DEBUG` is on**, and it is ignored in
  production.

**If it doesn't work:**
- **Safari can't connect:** the phone is on another network (a guest Wi-Fi isolates
  devices), or the macOS firewall is blocking Node. Allow "node" in **System Settings →
  Network → Firewall → Options**.
- **The location button says location is blocked:** in iOS, go to **Settings → Privacy &
  Security → Location Services → Safari Websites** and choose **While Using the App**. Then
  reload.

## Log in

- **The app:** click **Create account** (top right) on http://localhost:5173. The account lives
  only in your local database.
- **Django admin:** create a superuser, then sign in at http://localhost:8000/admin/:

  ```
  .venv/bin/python backend/manage.py createsuperuser
  ```

  The admin is the quickest way to inspect ingested rows and `IngestRun` provenance.

A forced restore (`make restore ... FORCE=1`) removes local accounts, so repeat both steps
after one.

## Checking the data makes sense

The unit suite (`pytest`) tests code against fixtures and never looks at your database.
`pytest -m data` does. It runs read-only against whatever `DATABASE_URL` points at, and both
a plain `pytest` and CI skip it. It checks that:

- at least one region holds all four layers (public land, trails, water, campsites)
- at least 75% of each region's campsites have water and a trail within 1 km
- every feature touches the bbox of the region it was ingested for (1 km tolerance)
- no more than 1% of trails are sidewalks, crossings, golf paths or non-path highways

The thresholds and the reasoning behind them are at the top of
`tests/data_checks/test_data_coherence.py`.

## Before you push

```
source .venv/bin/activate
ruff check . && ruff format --check . && pytest
cd frontend && npm run lint && npm run build && npm test
```

CI runs the same checks. Branch, commit and Jira rules are in `CLAUDE.md` and
`docs/CONTRIBUTING.md`.

## Troubleshooting

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

The frontend unit tests use Node's built-in TypeScript type stripping, which is on by
default from Node **22.18**. CI runs Node 22 (`.nvmrc`). On an older Node:

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
`DATABASE_URL`: that is path C. `make doctor` then reports the hosted path and checks it.
The production database is a separate matter; see `docs/deployment.md`.

## Measured setup times

Measured on 2026-11-08 on a MacBook (Apple Silicon, macOS, Docker Desktop), from a fresh
clone or a fresh container to `make doctor` passing every check with the full snapshot
loaded. "Warm" means the pip and npm download caches and the Docker base images were
already on the machine, as they are after any earlier project; a new machine adds their
downloads.

| Path | Step | Time |
|---|---|---|
| A, dev container (VS Code / Dev Containers CLI) | Build the image, uncached (base image already pulled) | 86 s |
| | `post-create.sh`: `make setup` in fresh volumes, download the 380 MB snapshot, restore, migrate | 94 s |
| | **Total, to `make doctor` all PASS** | **about 3 min** |
| A, in a GitHub Codespace | | Not measured yet: waiting on a teammate's run (TM05-160) |
| B, local Docker | `git clone`, then `.env` for a side-by-side copy (port 5442) | 5 s |
| | `make setup` (warm pip/npm caches, PostGIS image already pulled) | 30 s |
| | `make restore DUMP=$(make -s snapshot-url)`, including the 380 MB download | 81 s |
| | **Total, to `make doctor` all PASS** | **116 s** |
| C, hosted dev database | | Not measured yet: needs the hosted database to be created |

Other measurements from the same day:

- Restoring the snapshot from a local file into a throwaway PostGIS with TLS on and
  `sslmode=require`, with the PostGIS extension missing (so the restore created it): 88 s.
  With `NO_TERRAIN=1`: 16 s, and the database is 506 MB instead of 1.16 GB.
- `make dump` of the full database: 65 s, 380 MB.
- Inside the dev container, `make dev` served the page (200), `/api/health/` and
  `/api/map-data/` through the Vite proxy, accepted a `*.app.github.dev` host and refused
  an unknown one (403).

