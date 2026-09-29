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

A fresh database is empty. Load the committed sample with:

```
cd backend
python manage.py migrate
python manage.py seed
```

### What you should see after seeding

`seed` prints one line with a count for every layer:

```
Seeded sample dataset: 6 public lands, 25 trails, 134 water features, 15 campsites.
```

All four numbers should be non-zero. If any is `0`, the fixture is broken, not your setup.
Say so in the team channel rather than debugging your machine.

The sample covers one small box, about 7 x 7 km, around the Essex Chain Lakes in the
central Adirondacks (`-74.29, 43.825` to `-74.20, 43.885`). With the backend and frontend
running, open http://localhost:5173 and go to **Discover**. The map opens over the
Adirondacks, and the sample is the one patch of data in the lower half of the screen,
south of centre: green public land, blue lakes and streams, trail lines, and fifteen red
campsite markers along the lakes. Zoom in on it. **Everywhere else on the map is empty,
and that is expected**: only the full ingest (`docs/pipeline.md`) fills the rest of the
Northeast.

Trails and water are hidden below zoom 9 by design, so if you zoom far out and only see
public land and campsites, zoom back in.

To wipe the database back to a clean, seeded state at any time, run
`python manage.py reset_db` (add `--noinput` to skip the confirmation). Both are Django
management commands, so they work the same on macOS and Windows. The full Northeast
dataset comes from the ingestion pipeline instead (see `docs/pipeline.md`).

## Checking the data makes sense

The unit suite (`pytest`) tests code against fixture input and never looks at the rows in
your database. A second set of checks does. From the repo root, with the database seeded
or ingested:

```
pytest -m data
```

They run against whatever `DATABASE_URL` points at, read only, and are skipped by a plain
`pytest` and by CI. They check that:

- at least one ingest region holds all four layers (public land, trails, water, campsites)
- at least 75% of each region's campsites have water and a trail within 1 km
- every feature touches the bbox of the region it was ingested for (1 km tolerance)
- no more than 1% of trails are sidewalks, crossings, golf paths or non-path highways

A failure says what is wrong and where, for example
`region adirondacks has 0 campsites but 26,005 trails ... Did an ingest fail?`.
Run them after any ingest or after rebuilding the sample. The thresholds and the
reasoning behind them are at the top of `tests/data_checks/test_data_coherence.py`.

If Django reports `role "campsite" does not exist` even though Docker is running, another
PostgreSQL (e.g. from Homebrew) is probably holding port 5432 ahead of Docker. Set
`POSTGRES_PORT` to a free port such as 5434, use the same port in `DATABASE_URL`, and run
`docker compose up -d` again.

Pointing the app at a different database, including a hosted one, only means changing
`DATABASE_URL`. See `docs/deployment.md`.
