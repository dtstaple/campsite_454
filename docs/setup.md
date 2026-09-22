## Database (Docker + PostGIS)

Install Docker Desktop and make sure it's running. From the repo root, copy
`.env.example` to `.env` and set a local password. Then run `docker compose up -d`
to start PostgreSQL 16 with PostGIS 3.4. Verify it's working with
`docker compose exec db psql -U campsite -d campsite -c "SELECT postgis_version();"`.
Stop it with `docker compose down`; data persists in a named volume between restarts.

## Django to the database

Django reads the same repo-root `.env`, so there is only one file to maintain. Set a real
local password in **both** `POSTGRES_PASSWORD` and the password inside `DATABASE_URL` — they
have to match or the connection is refused. `DATABASE_URL` uses the `postgis://` scheme and
`localhost` as the host, because `manage.py` runs on your machine while Compose publishes
port 5432.

```
source .venv/bin/activate
pip install -r requirements.txt
cd backend
python manage.py migrate
```

Confirm the tables really landed in PostGIS rather than a stray SQLite file:

```
docker compose exec db psql -U campsite -d campsite -c "\dt"
```

GeoDjango needs GDAL and GEOS on the host: `brew install gdal geos` on macOS.

One gotcha worth knowing about. Django 5.1 searches for the GDAL library by name and only
knows about versions 3.0 through 3.8, so a current Homebrew GDAL (3.9+) is never found and
you get `Could not find the GDAL library`. The fix is already in `.env.example` — keep
`GDAL_LIBRARY_PATH` and `GEOS_LIBRARY_PATH` set:

```
GDAL_LIBRARY_PATH=/opt/homebrew/opt/gdal/lib/libgdal.dylib
GEOS_LIBRARY_PATH=/opt/homebrew/opt/geos/lib/libgeos_c.dylib
```

Those `/opt/homebrew/opt/...` paths are stable symlinks that follow Homebrew upgrades, so
they do not need updating when GDAL bumps. On Intel Macs substitute `/usr/local`. On Linux
the libraries are normally on the default search path and both variables can be omitted.

## Sample data

A fresh database is empty. Load the committed sample (about 160 features around Crawford
Notch, NH) with:

```
cd backend
python manage.py migrate
python manage.py seed
```

To wipe the database back to a clean, seeded state at any time, run
`python manage.py reset_db` (add `--noinput` to skip the confirmation). Both are Django
management commands, so they work the same on macOS and Windows. The full Northeast
dataset comes from the ingestion pipeline instead (see `docs/pipeline.md`).

If Django reports `role "campsite" does not exist` even though Docker is running, another
PostgreSQL (e.g. from Homebrew) is probably holding port 5432 ahead of Docker. Set
`POSTGRES_PORT` to a free port such as 5434, use the same port in `DATABASE_URL`, and run
`docker compose up -d` again.

Pointing the app at a different database, including a hosted one, only means changing
`DATABASE_URL`. See `docs/deployment.md`.
