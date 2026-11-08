# Run report: Sprint 9, TM05-160 and TM05-161 (2026-11-08)

An unattended run that implemented TM05-160 (portable dev environment) and the code side of
TM05-161 (deploy). Both PRs passed CI and were merged. Neither story was moved and no
worklogs were added. TM05-161 stays In Progress until the deployment is done.

## Summary

| Story | PR | Merged | AC met | AC waiting on a HUMAN step |
|---|---|---|---|---|
| TM05-160 Portable dev environment | [#123](https://github.com/dtstaple/campsite_454/pull/123) | Yes, 2026-11-08 17:32 UTC, CI green | 5 of 7 | Teammate verification; hosted path not measured |
| TM05-161 Deploy to production | [#124](https://github.com/dtstaple/campsite_454/pull/124) | Yes, 2026-11-08 17:51 UTC, CI green | Code side only (see below) | The deployment itself |

**New snapshot:** [dev-data-2026-11-08](https://github.com/dtstaple/campsite_454/releases/tag/dev-data-2026-11-08):

- The asset is `campsite-2026-11-08.dump`, **380 MB** (379,793,821 bytes), sha256
  `199816c6624fb42bcab3eba00dbf2876437159a74ee40d144d81edf42f54b634`.
- It restores to 1.16 GB, or 506 MB with `NO_TERRAIN=1`.
- `SNAPSHOT_URL` in the `Makefile`, `docs/setup.md`, `docs/data-status.md`, the README and
  onboarding all point at it, and the dev container restores it automatically.

## Things to know first

1. **The disk filled up, and Docker Desktop crashed (since recovered).**
   - The Mac had about 5 GB free at the start. The dev container builds and snapshot
     restores filled it at 16:47 UTC.
   - Docker Desktop's VM logged ext4 I/O errors and stopped.
   - I removed only what I had created: my two scratch copies of the dumps, then the dev
     container's containers, volumes and image. I force-quit the one hung Docker backend
     process; the VM was not running.
   - Docker came back and `campsite_db` did a normal WAL recovery. Its only redo was
     pytest's dropped test database.
   - Every row count matches what it was before, `pytest -m data` passes 4/4, and the full
     test suite passes against it.
   - **Free space is now about 2.6 GB.** There is about 4.7 GB of Docker build cache that I
     did not prune, because some of it may predate this run. Free some space before building
     more images (Docker Desktop → Troubleshoot → Clean / Purge data is all or nothing; the
     build cache can be reviewed with `docker buildx du`).
2. **Cold-air and wind terrain facts are empty in the snapshot.**
   - I re-ran `make terrain adirondacks` to fill the new TM05-147/148 columns. It failed
     twice, with 3 workers and then 1, in the `elevation_percentile` tool:
     `wasm trap: wasm unreachable instruction executed`.
   - The failed runs wrote nothing, so the snapshot has the 2026-11-02 terrain data.
   - This is a terrain-pipeline bug, outside these two stories; I did not change the
     pipeline. It is recorded in `docs/data-status.md` and the release notes.
3. **Your uncommitted `.env.example` was left untouched.**
   - Your working-tree version is an older, shorter one that drops most of the
     documentation, `DB_CONTAINER_NAME`, the CSRF/TLS variables and the Linux GDAL
     guidance.
   - My additions went into git without touching that file (index-only staging, then a
     stash and pop to switch branches; the byte-identical check passed).
   - `git diff .env.example` now also shows my 15 new lines as "removed". Your original diff
     is saved at
     `/private/tmp/claude-501/-Users-ds1244-Desktop-campsite454-campsite-454/37263f8e-392c-4476-9cb6-664108d78227/scratchpad/user-env-example.patch`.
4. **`make restore` now refuses a database that has data** unless `FORCE=1`, as the brief
   asked. Teammates who re-restore over existing data need `FORCE=1`.
5. **I used Node 22, not Node 20.** `.nvmrc`, CI and the frontend tests need 22.18 or newer;
   Node 20 cannot run `npm test`.

## TM05-160: portable dev environment

PR [#123](https://github.com/dtstaple/campsite_454/pull/123), merged. Commits `5e85895`,
`9d67169`, `01ae6d9` and `9b0ebe5`. Jira comment added with the PR link.

### AC

| AC item | Status | Evidence |
|---|---|---|
| A Codespace/dev container path and a hosted dev database path, both documented in docs/setup.md | **Met** (code and docs). The hosted database itself is HUMAN | `.devcontainer/`; docs/setup.md paths A and C |
| One snapshot with all data (geodata, enrichment, routing graph, terrain), loaded with one command, with no user data | **Met**, except the cold-air/wind gap above | dev-data-2026-11-08; `make restore DUMP=$(make -s snapshot-url)` |
| make doctor detects the path in use and checks it | **Met** | `scripts/db_path.py`, `scripts/doctor.py`, `tests/test_doctor.py` |
| The local Docker path still works | **Met** | Fresh clone to doctor all-PASS in 116 s |
| The time from clone to a running app is measured for each path | **Partly**: A (local) and B measured; a Codespace and C are not | docs/setup.md, "Measured setup times" |
| No credentials committed | **Met** | Only the documented dev placeholder password; `tests/test_deploy_config.py` checks render.yaml |
| Verified by one teammate, in a Jira comment | **Open (HUMAN)** | Message below |

### What was built

- **Dev container** (`.devcontainer/`):
  - The app container has Python 3.12, Node 22, Debian bookworm's GDAL 3.6 / GEOS 3.11 (the
    same as production), and `postgresql-client-16`, pinned so the PostgreSQL repository
    cannot replace GDAL.
  - A `db` service runs `postgis/postgis:16-3.4`. It is not published on the host, so it
    never clashes with `campsite_db`.
  - Ports 5173 and 8000 are forwarded.
  - `.venv` and `node_modules` are named volumes, and the container's environment overrides
    a host `.env`.
  - `post-create.sh` runs `make setup`, then restores the snapshot if the database is empty.
- **Codespaces:**
  - Vite, in the dev container only, listens on all interfaces, allows `*.app.github.dev`,
    and proxies `/api` to Django. The API is therefore same-origin and needs no CORS.
  - `settings.py` trusts the Codespace's forwarded 5173 and 8000 origins for CORS, CSRF and
    the admin, only while `DEBUG` is on.
- **`scripts/snapshot.py`**, behind `make dump` and `make restore`:
  - It works against any `DATABASE_URL`, including `sslmode`. The password goes through
    `PG*` environment variables, never the command line.
  - It uses `pg_restore` 16 locally, or runs it in the PostGIS image through Docker.
  - It creates PostGIS if it is missing.
  - It refuses a database that has data unless `FORCE=1`. `--if-empty` is for the dev
    container, and `NO_TERRAIN=1` restores every terrain table empty.
  - Dumps leave every personal table empty and are checked, and a dump that fails the check
    is deleted. A test fails if a new model pointing at a user is not covered.
- **`make doctor`** prints the path and checks it. The checks that differ by path: the
  Compose settings or the database host's reachability, `sslmode` on a hosted URL, the
  PostgreSQL 16 client tools, and which ports are checked. Each failure gets a path-specific
  FIX.

### Measurements (2026-11-08, MacBook Apple Silicon, Docker Desktop)

| What | Time |
|---|---|
| Path A: uncached dev container image build (base image already pulled) | 86 s |
| Path A: `post-create.sh` in fresh volumes (setup, 380 MB download, restore, migrate) | 94 s |
| **Path A total, to `make doctor` all PASS** | **about 3 min** |
| Path B: clone and `.env` 5 s, `make setup` 30 s, `make restore` with download 81 s | **116 s** total |
| Path C, and A in a real Codespace | Not measured (HUMAN) |
| `make dump` | 65 s, 380 MB |
| Restore from a local file into a throwaway PostGIS over TLS, with PostGIS missing | 88 s; counts match; personal tables empty; `pytest -m data` 4/4 |
| Restore with `NO_TERRAIN=1` | 16 s, 506 MB |

- Inside the dev container, `make doctor` passed every check.
- `make dev` served the page, and `/api` through the proxy, with 200.
- A `*.app.github.dev` host header got 200; an unknown host got 403.

### Decisions made along the way (conservative option, recorded)

- **The Neon free tier is too small.** It is 1 GB per project; the full snapshot is
  1.16 GB.
  - Path C is documented with Neon branches and `NO_TERRAIN=1` (506 MB) for the free tier,
    or a paid plan for everything.
  - I first tried skipping only the zones table and withdrew it. The app decides "terrain
    checked" from `TerrainRun`, so Find campsites would have claimed every spot is outside
    a pooling-risk zone. Without any terrain rows it honestly says "not checked".
- **The snapshot data.** Before dumping, I ingested `osm-landmarks` for both regions into
  the local database, which had 0 landmarks. That gave 1,861 and 619.
- **The Makefile** now reads only `COMPOSE_PROJECT_NAME` from `.env`. `-include .env` exported
  every `.env` line over the process environment, so the Mac's GDAL path and `localhost`
  database leaked into the dev container. The dev container test found this.

## TM05-161: deploy (code side)

PR [#124](https://github.com/dtstaple/campsite_454/pull/124), merged. Commits `9cf8b83`,
`4637551`, `1bad488` and `fa05f98`. Jira comment added. **Nothing live changed.**
`restore_production.sh` was never run against a hosted database.

### Inventory of TM05-113

- **Already on main:**
  - `backend/Dockerfile`: Debian GDAL, `collectstatic` and whitenoise, non-root, gunicorn,
    migrate on start.
  - `render.yaml`: free database, API and static site.
  - Fail-closed production settings, with tests.
  - `scripts/smoke_test.sh`.
- **`render.yaml` is not tied to `dtstaple/campsite_454`.** It has no `repo:` field. A
  Blueprint belongs to the repository it was applied from, and the live one was applied
  from `BleronBalidem/campsite_454`.
  **HUMAN: Bleron switches the Render service to dtstaple/campsite_454** (or a new
  Blueprint is applied from it, checklist below).

### AC

| AC item | Status |
|---|---|
| Managed PostgreSQL + PostGIS with backups | Code ready (paid `basic-256mb`, point-in-time recovery, PostGIS created by the restore). Creating it is HUMAN |
| The backend from the existing Dockerfile, with migrations on deploy | Code ready (`preDeployCommand`). Live deploy is HUMAN |
| The frontend over HTTPS from a CDN-backed host | Code ready (Render static site). Live is HUMAN |
| Production data loaded from the snapshot | Script ready and tested locally. Running it is HUMAN |
| Production settings, with secrets only in the host | **Met in code** and verified in the image |
| The basemap key works on the domain, and attributions are shown | HUMAN (Stadia domain list; attribution is MapLibre's control fed by the style) |
| End to end on the live URL, including GPS on a real iPhone | HUMAN |
| The smoke test passes, and a health check is configured | Health check configured. Smoke test 19/19 locally; on live, HUMAN |
| Every merge to main deploys after CI passes | **Met in code**. Verified a no-op on main until the secrets are added (HUMAN) |
| docs/deployment.md covers cost, redeploy, data refresh, rollback and credentials | **Met** |

### What changed

- **`render.yaml`:**
  - The database is Postgres 16 on `basic-256mb` with a 5 GB disk.
  - The API is on `starter` with `preDeployCommand: python manage.py migrate --no-input`,
    `healthCheckPath: /api/health/` and `MIGRATE_ON_START=False`.
  - The static site has an SPA rewrite, plus immutable `/assets/*`, a `no-cache`
    `index.html` and security headers.
  - `autoDeployTrigger: "off"` on both services, and no secret values.
  - The field names (`preDeployCommand`, `autoDeployTrigger`, `diskSizeGB`, `basic-256mb`)
    came from Render's Blueprint reference as summarised by search. Render validates the
    file when the Blueprint is applied; fix any field it rejects then.
- **`backend/Dockerfile`:** `MIGRATE_ON_START` (default `True`), `GUNICORN_TIMEOUT`
  (default 180 s, because a cold Find campsites took 129 s once), and a `HEALTHCHECK`.
- **`.github/workflows/ci.yml`** gets an additive `deploy` job (see Edits below).
- **`scripts/restore_production.sh`:** confirms the host, refuses a non-empty database
  without `--force`, creates PostGIS, restores and migrates.
- **`scripts/smoke_test.sh`:** adds a vector tile, a trail panel, Find campsites and route
  planning, and deletes its throwaway user at the end.
- **`docs/deployment.md`** is rewritten, and `tests/test_deploy_config.py` adds 13 tests.

### Measurements (local, production settings)

- **The image:** built in 90 s, 1.41 GB (arm64; Render builds amd64).
  - Pre-deploy migrate: nothing to apply.
  - `check --deploy`: only the HSTS subdomains and preload warnings, which are deliberately
    off.
- **With `BEHIND_TLS_PROXY=True` and a 512 MB limit:**
  - Health is 200 over HTTP; other paths 301 to HTTPS, and 200 via `X-Forwarded-Proto`.
  - whitenoise serves the CSS. HSTS is sent and the CSRF cookie is `Secure`.
  - The Docker health check is `healthy`.
- **The smoke test** against the image and a production frontend build: **19/19 PASS**.
- **Memory:** 367 MB of 512 MB with 2 workers, both holding the routing graph.
  - The first route in a fresh worker took 36 s, while it loaded the graph; then 0.2–0.3 s.
- **Estimated cost:** about **$14.50 a month** (database $6 + $1.50 storage, API $7, static
  site $0).

## Edits to CI, the Makefile, and teammates' areas

- **CI (`.github/workflows/ci.yml`):** additive only. A new `deploy` job needs `quality` and
  `frontend`, runs only on pushes to `main`, and calls the deploy hooks only when the
  `RENDER_DEPLOY_HOOK` and `RENDER_DEPLOY_HOOK_WEB` secrets exist. The existing jobs are
  unchanged.
- **`Makefile`:**
  - Reads only `COMPOSE_PROJECT_NAME` from `.env`.
  - `setup` runs Compose only on the Docker path.
  - `dump` and `restore` call `scripts/snapshot.py`.
  - New `FORCE`, `NO_TERRAIN` and `snapshot-url`.
  - Removed the now-unused `DB_CONTAINER_NAME`, `POSTGRES_USER` and `POSTGRES_DB` make
    variables and `PERSONAL_TABLES`, which moved to `snapshot.py`.
  - `SNAPSHOT_URL` is updated.
  - **Behaviour change:** `make restore` into a database with data needs `FORCE=1`.
- **Teammates' areas.** No teammate's Sprint 9 story (TM05-130, 131, 133, 134, 162, 163) was
  touched. Files in teammates' areas that changed:
  - Bleron Balidemaj (Docker, deployment config): `backend/Dockerfile` and `render.yaml`. He
    should review #124.
  - Abdulrahman Shaalan (Django backend): `backend/config/settings.py`, which gains the
    dev-only Codespaces origins block (DEBUG only).
  - Sahaj Soni (frontend): `frontend/vite.config.ts`, which gains a dev-container-only
    server block. `optimizeDeps.exclude` is kept and the phone mode is unchanged.
- **Local state changed:**
  - In my local database: `osm-landmarks` ingested for both regions, and two failed
    `TerrainRun` provenance rows.
  - A smoke-test user was created and then deleted.
  - Release `dev-data-2026-11-08` published.
  - `dumps/campsite-2026-11-08.dump` (380 MB, gitignored) is still in the checkout.

## HUMAN CHECKLIST for TM05-161

Never paste a database URL, password or hook URL into chat, Jira or git.

1. **Render access.**
   - Either Bleron, as owner of the Render workspace that runs TM05-113, adds Davis as a
     member (Workspace Settings → Members → Invite), **or** create a new account at
     https://dashboard.render.com/register (Sign up with GitHub).
   - Then, under Account Settings → GitHub, grant Render access to `dtstaple/campsite_454`.
2. **Apply the Blueprint from the main repo.** Dashboard → **New → Blueprint** →
   `dtstaple/campsite_454` → branch `main` → Render reads `render.yaml`.
   - If the old TM05-113 services exist in the same workspace, choose new names, or have
     Bleron delete the old free services first. Keep `campsite-web-tt5e` running until the
     new site works.
3. **Enter the four `sync: false` values** when prompted. Placeholders are fine until the
   URLs exist.
   - `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`: `https://<campsite-web>.onrender.com`.
   - `VITE_API_BASE_URL`: `https://<campsite-api>.onrender.com`.
   - `VITE_MAP_STYLE_URL`: `https://tiles.stadiamaps.com/styles/alidade_smooth_dark.json`.
4. **Confirm the plans and costs** on the Blueprint review page: `campsite-db`
   `basic-256mb` with 5 GB, `campsite-api` `starter`, `campsite-web` free. Add a payment
   method (Workspace → Billing). Click **Apply**.
5. **Check the database:** **campsite-db → Info**. PostgreSQL 16 and status Available.
   Under **Recovery**, note the point-in-time recovery window.
6. **Restore the data**, from your Mac with `make setup` done:
   - Copy **campsite-db → Connect → External Database URL**.
   - Run:
     ```
     scripts/restore_production.sh '<External URL>?sslmode=require' \
       https://github.com/dtstaple/campsite_454/releases/download/dev-data-2026-11-08/campsite-2026-11-08.dump
     ```
     Type the host name when asked. If it says the database has data (the API's first
     deploy may have migrated it), re-run with `--force`.
   - Expect the row counts: 1,500 campsites, 92,663 graph edges, 694,544 terrain zones.
7. **Fix the env vars with the real URLs.**
   - **campsite-api → Environment:** set both origins to the real frontend URL (no trailing
     slash), then **Save, rebuild, and deploy**.
   - **campsite-web → Environment:** set `VITE_API_BASE_URL` to the real API URL, then
     **Manual Deploy → Clear build cache & deploy**.
8. **Stadia:** stadiamaps.com → the property used in TM05-113 → Authentication → add the
   new frontend domain. Bleron has the account.
9. **Deploy and watch.**
   - campsite-api → **Events**: the build, then "Pre-deploy command succeeded", then "Deploy
     live".
   - campsite-web: build succeeded.
10. **Smoke test from your Mac:**
    `scripts/smoke_test.sh https://<campsite-api>.onrender.com https://<campsite-web>.onrender.com`.
    Expect every line PASS. Paste the output, which contains no secrets, into a TM05-161
    comment.
11. **Before a demo:** `DATABASE_URL='<External URL>?sslmode=require' make prewarm` caches
    Find campsites for the demo trails.
12. **iPhone, on the live frontend URL in Safari:**
    - The map, the basemap and its attribution (bottom right).
    - **Location** shows the GPS dot (Settings → Privacy → Location Services → Safari
      Websites → While Using).
    - **Follow me**, a trail panel, Find campsites and planning a route.
    - Share → **Add to Home Screen**.
    - Note the results in a TM05-161 comment.
13. **Add the deploy hooks.**
    - campsite-api → **Settings → Deploy Hook** → copy, then GitHub → `dtstaple/campsite_454`
      → Settings → Secrets and variables → Actions → **New repository secret**
      `RENDER_DEPLOY_HOOK`.
    - Repeat for campsite-web as `RENDER_DEPLOY_HOOK_WEB`.
    - The next merge to `main` should show the CI `deploy` job running "backend deploy
      triggered".
14. **Retire the old deployment** once the new one passes: Bleron deletes the free TM05-113
    services or the fork's Blueprint. Then update the two URLs at the top of
    `docs/deployment.md`.
15. **Then** move TM05-161 to Done, once it is merged, live and verified.

## Other HUMAN items

- **TM05-160, teammate verification** (AC, left unchecked). Send the message below.
- **TM05-160, path C:** create the Neon project and a branch per developer (docs/setup.md,
  path C), then time a fresh clone to a running app and add it to "Measured setup times".
- **Free disk space** on this Mac (about 2.6 GB free).
- **The terrain bug:** `elevation_percentile` traps in `make terrain adirondacks`. After it
  is fixed, re-run terrain, `make dump`, and publish a new snapshot.

### Message to send teammates for TM05-160

> Hi all, the portable dev environment for TM05-160 is merged. Could one of you (Bleron
> ideally, since it's Docker) try it and comment on TM05-160?
>
> 1. Go to https://github.com/dtstaple/campsite_454 → **Code → Codespaces → Create codespace
>    on main** (pick 4-core if it asks).
> 2. Wait for the terminal to say "Dev container ready in N s". It builds, installs, and
>    restores the data snapshot by itself, which takes a few minutes the first time.
> 3. Run `make doctor`, then `make dev`, and open the forwarded port **5173** (Ports tab, the
>    globe icon).
> 4. Comment on TM05-160 with:
>    - whether it worked
>    - the "Dev container ready in N s" number, and roughly how long from clicking Create
>      to seeing the map
>    - the `make doctor` output, and a screenshot of the map
>
> The basemap may stay blank on the github.dev address (Stadia's keyless tiles are for
> localhost only); the trails and campsites should still draw. Stop the codespace when
> you're done, because it uses our free hours. Setup guide: docs/setup.md, path A.
