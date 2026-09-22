# Deployment

This document explains what it would take to host CampSite somewhere other than a
developer's laptop. **CampSite is not deployed anywhere today.** Nothing here has been run
against a real hosting provider. The last section lists exactly what was tested and what
wasn't, so read that before relying on any single claim.

## The three pieces

A running CampSite is three separately deployable parts:

1. **A PostGIS database** holds the geospatial features (public land, trails, water,
   campsites) and the ingest history.
2. **The Django backend** (`/backend`) serves the JSON map-data API documented in
   `docs/api.md`. It is the only piece that talks to the database. The ingestion pipeline
   (`manage.py ingest`) lives in the same codebase but is a batch job, not part of the
   web server.
3. **The frontend** (`/frontend`) is a React + MapLibre single-page app. `npm run build`
   compiles it to plain static files in `frontend/dist/`.

The browser downloads the frontend's static files from wherever they are hosted. The
JavaScript then calls the backend at `VITE_API_BASE_URL`, and the backend queries PostGIS
through `DATABASE_URL`. The frontend never touches the database, and the database never
needs to be reachable from the public internet. Only the backend needs network access
to it.

## The database: PostGIS, not just Postgres

The app requires the **PostGIS extension**, so a plain PostgreSQL database is not enough.
Every geometry column, spatial index, and bounding-box query in `/backend/api` depends on
PostGIS types and functions. GeoDjango's first `migrate` runs
`CREATE EXTENSION IF NOT EXISTS postgis`, and against a server without PostGIS installed
that fails before any table is created. PostGIS is a server-side extension that has to be
installed on the database host. Nothing in our code can install it, so a hosting provider
is only usable if it offers PostGIS.

When choosing a managed Postgres, check three things in its current documentation:

- **PostGIS is on the provider's list of supported extensions.** Most large managed
  services offer it, but some free tiers don't.
- **Who is allowed to run `CREATE EXTENSION postgis`.** PostGIS is not a "trusted"
  extension, so on many providers only an admin role can enable it. The simplest pattern
  is to enable it once as the admin (`CREATE EXTENSION postgis;`) and let the app's role
  do everything else. After that, migrate's `IF NOT EXISTS` is a no-op. `reset_db` never
  drops or recreates the extension, so it keeps working under a non-admin role.
- **Versions.** Development and CI use PostgreSQL 16 with PostGIS 3.4
  (`postgis/postgis:16-3.4`). A hosted database should match the Postgres major version,
  especially if data is ever moved across with `pg_dump`.

Providers give out connection strings like `postgres://user:pass@host:port/db?sslmode=require`.
That string is the whole of the configuration: `settings.py` always forces the PostGIS
engine regardless of the URL scheme, and query parameters such as `sslmode=require` are
passed through to the driver. Characters like `@` or `/` in a password must be
percent-encoded (`@` becomes `%40`). The settings keep connections open for 10 minutes
(`conn_max_age=600`), so a small plan's connection limit needs to cover roughly one
connection per web-server worker.

**Getting data into a hosted database.** A fresh database is empty, and there are three
ways to fill it:

- `python manage.py seed` loads the committed sample (Crawford Notch, NH: about 160
  features). This is enough to show the app working.
- `python manage.py ingest <source> <region>` runs the real pipeline straight into the
  hosted database from any machine with network access. This is the reproducible way to
  get the full ~92k features. It takes a while and needs `RIDB_API_KEY` for campsites.
- `pg_dump`/`pg_restore` copies an existing local database. This is fast, but it needs
  Postgres client tools and matching versions.

## The backend: getting GDAL and GEOS

This is the least obvious part of deploying a GeoDjango app. `django.contrib.gis` loads
the **GDAL** and **GEOS** C libraries when Django starts, and it refuses to start if it
can't find them. They are operating-system libraries, not Python packages, so
`pip install -r requirements.txt` does not provide them.

On a Mac, developers install them with Homebrew and point Django at them in `.env`:

```
GDAL_LIBRARY_PATH=/opt/homebrew/opt/gdal/lib/libgdal.dylib
GEOS_LIBRARY_PATH=/opt/homebrew/opt/geos/lib/libgeos_c.dylib
```

Those are Apple Silicon Homebrew paths. They don't exist on Windows, Linux, Intel Macs, or
any hosting platform, so **these two variables are development-only and must not be set in
production.** They are needed on macOS only because Django 5.1 looks for GDAL by versioned
file name, only for versions 3.0 through 3.8, and Homebrew currently ships a newer GDAL.
When the variables are unset, Django searches the system's default library paths. That
works wherever a supported GDAL version is installed the normal way.

The dependable way to provide the libraries in a deployed environment is a **Docker image
that installs them from the Linux distribution's package manager**. Debian bookworm ships
GDAL 3.6 and GEOS 3.11, which Django finds automatically. This image was built and used to
run the whole app for this story (migrations, seeding, the API server, and the full test
suite):

```dockerfile
FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgdal32 libgeos-c1v5 libproj25 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /app
```

It installs only the runtime libraries (about 590 MB uncompressed), not the `-dev`
headers, because nothing in `requirements.txt` compiles against GDAL. It is a starting
point, not a production image. It still needs the application code copied in, a
production web server (see below), a non-root user, and a start command. CI
(`.github/workflows/ci.yml`) takes the same approach on an Ubuntu runner with `apt-get`.

The alternative is a platform that provides GDAL itself, such as a buildpack or a
platform-specific package list. That can work, but the platform has to give Django a GDAL
version it recognises (3.0–3.8 as of Django 5.1). If it ships something newer,
`GDAL_LIBRARY_PATH` has to be set to that platform's own path. A Docker image avoids that
guesswork.

The same image is also a way for **Windows developers** to avoid installing GDAL natively,
which is notoriously awkward on Windows (typically OSGeo4W or conda). Nobody on the team
has tested that path on Windows yet.

## Environment variables

Every variable is read in `backend/config/settings.py` or `docker-compose.yml`, or baked
into the frontend build.

| Variable | Production | Notes |
|---|---|---|
| `DATABASE_URL` | **Required** | The only database setting. Django refuses to start without it. Add `?sslmode=require` for hosted databases. |
| `SECRET_KEY` | **Required** | Must be a long random value. If unset, settings fall back to an insecure dev key **without complaining**, so a missing value in production would go unnoticed. |
| `DEBUG` | **Must be `False`** | If unset it defaults to `True`, so production must set it explicitly. With `DEBUG=True`, error pages leak settings and code. |
| `ALLOWED_HOSTS` | **Required** | Comma-separated hostnames the API is served on, e.g. `api.example.com`. The default only allows localhost. |
| `CORS_ALLOWED_ORIGINS` | **Required** | The frontend's exact origin, e.g. `https://campsite.example.com`. Without it the browser blocks every API call from the deployed frontend. |
| `RIDB_API_KEY` | Ingestion only | Needed where `manage.py ingest ridb` runs. The web server never uses it. |
| `GDAL_LIBRARY_PATH`, `GEOS_LIBRARY_PATH` | **Do not set** | Development-only macOS paths; see above. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT` | Not used | Only read by `docker-compose.yml` to create the local dev database. |
| `VITE_API_BASE_URL` | **Build-time** | Read by the frontend build, not by any server. See the next section. |

Secrets belong in the host's secret or environment configuration, never in a committed
file. Only `.env.example` files with placeholders are in git.

## The frontend: a static build

`npm run build` (run in `/frontend`) type-checks the app and writes `index.html` plus
hashed JS and CSS bundles to `frontend/dist/`. Those files are the whole frontend. Any
static host can serve them: a CDN or static-site service, an object-storage bucket with a
website endpoint, or the same nginx that fronts the backend. No Node.js server runs in
production.

**`VITE_API_BASE_URL` is baked in at build time, not read at runtime.** Vite replaces
`import.meta.env.VITE_API_BASE_URL` with the literal string while building, so the value
in effect when `npm run build` runs is hard-coded into the JavaScript bundle. Two things
follow from that:

- Pointing the frontend at a different backend means **rebuilding it**. Changing an
  environment variable on the static host does nothing. Set the value in
  `frontend/.env.production` (gitignored) or in the build environment before building.
- The value is **public**. Anyone can read it in the bundle, so no `VITE_*` variable may
  ever hold a secret.

As of this story the app only logs `VITE_API_BASE_URL`; it doesn't fetch map data yet.
The build also warns that the JS bundle is ~1.2 MB (343 KB gzipped), almost all of it
MapLibre. That's acceptable, but it could be split later. The basemap style comes from
`demotiles.maplibre.org`, a demo service that isn't meant for production traffic. A real
deployment needs a proper tile provider.

## What is still missing for a real deployment

The app is portable across databases today, but it isn't production-ready. Running
`manage.py check --deploy` with `DEBUG=False` and a real `SECRET_KEY` reports four
warnings, and several more gaps exist beyond those:

- **HTTPS.** Nothing terminates TLS. That is usually done by the platform's load balancer
  or a reverse proxy. Once HTTPS is in place, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`,
  `SESSION_COOKIE_SECURE`, and `CSRF_COOKIE_SECURE` should be turned on (the four
  `check --deploy` warnings), along with `SECURE_PROXY_SSL_HEADER` if a proxy terminates
  TLS.
- **A production web server.** `manage.py runserver` is a development server. The backend
  needs a WSGI server such as gunicorn, which isn't in `requirements.txt` yet, usually
  behind nginx or the platform's router.
- **`DEBUG=False`, `ALLOWED_HOSTS`, and `CORS_ALLOWED_ORIGINS`** must be set as described
  above. Because of the defaults in `settings.py`, forgetting them fails open (debug on,
  dev secret key) rather than failing loudly. It would be worth making production refuse
  to start without them.
- **Static files for Django itself.** The API returns JSON and needs no static files, but
  the Django admin does. `STATIC_ROOT` isn't set, so `collectstatic` currently fails with
  `ImproperlyConfigured`. A deployment needs `STATIC_ROOT` plus either WhiteNoise or the
  reverse proxy to serve that directory.
- **Migrations as a release step.** Run `manage.py migrate` against the production
  database on each deploy, before the new code takes traffic.
- **Backups and monitoring.** Managed databases usually offer automated backups, which
  should be switched on. There is no error reporting or uptime monitoring yet.
- **Keep dev tools away from production data.** `reset_db` drops every table. It refuses
  to run when `DEBUG=False` unless given `--force`, but the real protection is never
  pointing a developer's `DATABASE_URL` at the production database.

## Moving between databases (dev tooling)

Three management commands in `backend/devdata` make any database usable in one step.
They are plain Python, so they run identically on macOS, Windows, and Linux, with no
shell scripts, Makefiles, or Postgres client tools. Run them from `/backend` with
`DATABASE_URL` pointing at the target:

- `python manage.py seed` loads the committed sample fixture
  (`backend/devdata/fixtures/sample.json`, ~230 KB) into an empty, migrated database. It
  refuses if the database already has features, because fixture rows have fixed primary
  keys and would overwrite real rows.
- `python manage.py reset_db` drops every app table, re-runs migrations, and seeds. It
  asks for confirmation; `--noinput` skips the prompt. It never drops the schema or the
  PostGIS extension.
- `python manage.py build_sample` regenerates the fixture from the live sources for the
  sample area. It needs network access and an **empty scratch database**, and is only
  needed when the models or adapters change. The committed sample has **no campsites**
  because it was built without an `RIDB_API_KEY`. Rebuilding it with a key set adds them.

The sample is a small bounding box around Crawford Notch, NH, with geometries clipped to
the box. A box in the Adirondacks was tried first, but PAD-US's Forest Preserve polygon
there has invalid geometry and the pipeline skips it. The same thing happens to the large
White Mountain National Forest parcel. That is a data-quality issue for the pipeline
itself: the largest public-land units may be missing from the full database too.

## What was tested and what wasn't

Tested for this story on macOS (Apple Silicon), with the backend running in the Debian
image above:

- The same unchanged code ran against **two separate PostGIS servers**, switched only by
  changing `DATABASE_URL`. One was the Compose database; the other was a throwaway
  `postgis/postgis:16-3.4` container published on port 5433. On each, `migrate`, `seed`
  or `reset_db`, and `runserver` succeeded, and `/api/health/`, `/api/map-data/`,
  `/api/trails/`, `/api/water/` and `/api/campsites/` returned identical results
  (101 trails, 53 water features).
- `reset_db` was run repeatedly. Cancelling the prompt, refusing under `DEBUG=False`, and
  `seed` refusing a non-empty database were all exercised. PostGIS and its
  `spatial_ref_sys` table survive a reset.
- A hosted-style URL (`postgres://…?sslmode=require` with a percent-encoded password)
  parses to the PostGIS engine with `sslmode` passed through.
- `ruff check`, `ruff format`, and the full pytest suite pass. The suite includes tests
  for the seed, reset, and sample tooling.
- `npm install` and `npm run build` succeed.
- `manage.py check --deploy` and `collectstatic` were run to find the gaps listed above.

Not tested:

- **A real hosting provider.** The second database was a local container. A managed
  service adds TLS, network allow-lists, connection limits, and extension permissions,
  none of which were exercised.
- **Windows.** The commands contain nothing OS-specific, and the fixture is UTF-8 with
  `\n` line endings, but nobody has run them on Windows. A Windows teammate should run
  `migrate`, `seed`, and `reset_db` once.
- **A production web server, HTTPS, or a static host** serving `frontend/dist`.
- **The built frontend talking to a deployed backend.** The frontend doesn't call the API
  yet.

## Local development gotchas found along the way

- **Another Postgres on port 5432.** If a native PostgreSQL (e.g. from Homebrew) is
  running, it can take `localhost:5432` ahead of Docker, so Django reaches the wrong
  server and fails with `role "campsite" does not exist`. Set `POSTGRES_PORT=5434` (or any
  free port) in `.env`, use the same port in `DATABASE_URL`, and run
  `docker compose up -d` again.
- **The PostGIS image is x86-only.** `postgis/postgis:16-3.4` has no ARM build, so on
  Apple Silicon Docker runs it under emulation. It works, just more slowly.
