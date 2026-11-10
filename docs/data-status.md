# Data status

What data the team snapshot holds, region by region, and how the derived facts were
measured. Update it whenever a region is ingested or enriched, or a new snapshot is
published. Setup and restore instructions are in `docs/setup.md`.

## Current snapshot

[dev-data-2026-11-10](https://github.com/dtstaple/campsite_454/releases/tag/dev-data-2026-11-10)
(483 MB download, about 1.36 GB restored), published 2026-11-10 under TM05-163.

```
make restore DUMP=https://github.com/dtstaple/campsite_454/releases/download/dev-data-2026-11-10/campsite-2026-11-10.dump
```

It was dumped with `make dump` (`scripts/snapshot.py`) from a database restored from
dev-data-2026-11-08, after `make terrain REGION=white-mountains-nh` had run on it. Nothing
personal is in it: the tables matching `PERSONAL_TABLES` (accounts, tokens, sessions, the
admin log, saved campsites, scoring weights, waypoints, trip plans, hikes, saved trails)
are dumped empty, and both the dump's own check and `scripts/snapshot.py check` confirmed
that no personal table has rows.

| Table | Rows | Region |
|---|---|---|
| Campsites | 1,500 | both |
| Campsite facts (enrichment) | 1,499 | both |
| Trails | 25,663 | both |
| Named routes, route facts | 452, 452 | both |
| Water features | 76,551 | both |
| Public land | 2,488 | both |
| Peaks and trailheads | 2,480 (1,861 + 619) | both; `osm-landmarks` re-run on 2026-11-08 for both regions |
| Road connectors | 70,773 | Adirondacks (TM05-137) |
| Routing graph edges, graph builds | 92,663, 4 | Adirondacks (TM05-119/137/149) |
| Terrain facts | 1,499 (743 + 756) | both: the Adirondacks from the 2026-11-02 run, the White Mountains from the 2026-11-10 run (TM05-163) |
| Terrain zones | 826,696 (694,544 + 132,152) | both, as above |
| Cached analyses | 8,737 | both |

**New since dev-data-2026-11-08:** terrain facts and zones for the White Mountains, for
all 756 campsites and every terrain fact, cold air, wind and sun hours included.
`docs/terrain-analysis.md` ("Measured: the White Mountains") has the run's coverage,
runtime and memory. The Adirondacks rows are unchanged.

**How it was checked (2026-11-10).** Restored with `make restore` from the local file into
a new, empty database on the local `postgis/postgis:16-3.4` container: PostGIS was
created, the restore took 47 s, and `migrate` found nothing to apply. The row counts above
are from that restore, the terrain facts split 743 Adirondacks and 756 White Mountains,
and `pytest -m data` passed 4/4. sha256 of the dump:
`ce63131e24dae9cc0597577bf50b93a4b477ffa1ab492d8d68816061893625f3`.

The previous snapshot,
[dev-data-2026-11-08](https://github.com/dtstaple/campsite_454/releases/tag/dev-data-2026-11-08)
(380 MB, TM05-160), is kept as a release. It matches this one except that it has no White
Mountains terrain.

**Known gap: cold air and wind in the Adirondacks.** The Adirondacks `cold_air` and `wind`
terrain facts (TM05-147/148) are empty; the White Mountains run filled them for its
region. `make terrain adirondacks` was re-run on 2026-11-08 to fill them and failed twice (3 workers, then 1) in the `elevation_percentile` tool with a WASM trap ("wasm
`unreachable` instruction executed"). The failed runs wrote no facts or zones, so the
terrain data is from the last successful run, 2026-11-02. Adirondacks campsite panels show
cold air and wind as not available until the terrain run is fixed and a new snapshot is published.

**How the 2026-11-08 snapshot was checked.** Restored with `make restore` into a throwaway
`postgis/postgis:16-3.4` container with TLS on and `sslmode=require`, after dropping its
PostGIS extension: the restore created PostGIS, restored in 88 s from the local file, and
`migrate` found nothing to apply. Every row count above matched the source; every personal
table was empty; `pytest -m data` passed 4/4. A second `make restore` without `FORCE=1`
refused, naming the tables with data. With `NO_TERRAIN=1` (every terrain table restored
empty, for a 1 GB hosted free tier; docs/setup.md, path C) the restored database is
506 MB. The throwaway containers were then deleted.

The sections below describe how the data in it was built, oldest first. The previous
snapshot, [dev-data-2026-10-13](https://github.com/dtstaple/campsite_454/releases/tag/dev-data-2026-10-13)
(104 MB, TM05-90), is kept as a release but no longer matches the app: it has no routing
graph or terrain. The sections from here to "How the 2026-10-13 snapshot was
checked" describe it.

## The 2026-10-13 snapshot

[dev-data-2026-10-13](https://github.com/dtstaple/campsite_454/releases/tag/dev-data-2026-10-13)
(104 MB), published 2026-10-13 under TM05-90.

```
make restore DUMP=https://github.com/dtstaple/campsite_454/releases/download/dev-data-2026-10-13/campsite-2026-10-13.dump
```

It was built from the previous snapshot (`dev-data-2026-10-05`), migrated to
`geodata.0008`, plus the four runs recorded below. Nothing else was re-ingested, so
trails, water, public land, routes and route profiles are as of 2026-10-05.

| Table | Rows |
|---|---|
| Campsites | 1,501 (660 RIDB, 841 OSM; 180 are lean-tos) |
| Campsite facts (enrichment) | 1,500 |
| Trails | 25,663 |
| Water features | 76,551 |
| Public land | 2,488 |
| Named routes | 452 |
| Peaks | 1,748 (1,707 with an elevation) |
| Trailheads | 91 |

Peaks and trailheads are Adirondacks only; `osm-landmarks` has not been run for the White
Mountains.

## White Mountains enrichment (TM05-90)

`python manage.py enrich_campsites white-mountains-nh`, run 2026-10-13 against the
restored 2026-10-05 snapshot. It was the first enrichment of this region: the campsites
had no facts before it.

| Measure | Value |
|---|---|
| Campsites | 756 (660 RIDB, 96 OSM) |
| Runtime | 182.4 s, of which 148.6 s was 3DEP terrain |
| Public land unit | 669 (88.5%) |
| Named water | 756 (100.0%) |
| Named trail | 756 (100.0%): 321 by route, 435 by way |
| Elevation + slope | 756 (100.0%) |
| Any OSM tag | 59 (7.8%) |
| Shelter kind | 12 (1.6%) |
| Display name | 756 (100.0%); derived for 19 of 19 unnamed |

"Any OSM tag" and "shelter kind" are low because 660 of the 756 sites come from RIDB,
which carries no OSM tags.

### Failures

- **3DEP returned HTTP 502 twice** during the terrain step. Both were retried
  automatically and succeeded, so no site is missing elevation or slope. Nothing to fix.
- **87 sites (11.5%) have no public land unit.** Not investigated: whether they sit on
  private land or in a gap in the ingested PAD-US data is not known.
- **One campsite has no facts:** OSM `way/1022435632`, Kingdom Campground, at latitude
  44.5524. The region's bounding box ends at 44.55, so it is outside every region and no
  enrichment run selects it. How it came to be ingested was not investigated. Left as it
  is.

## Adirondacks runs for the 2026-10-13 snapshot

The previous snapshot predated the lean-tos (TM05-75) and the peaks and trailheads
(TM05-89), so these were run before the snapshot was taken.

| Command | Result | Time |
|---|---|---|
| `ingest osm-campsites adirondacks` | 743 rows, success | 19 s |
| `ingest osm-landmarks adirondacks` | 1,839 rows, success | 40 s |
| `enrich_campsites adirondacks` | 744 campsites | 137.0 s, of which 106.9 s terrain |

Adirondacks enrichment coverage after that run: public land unit 668 (89.8%), named water
744 (100.0%), named trail 736 (98.9%), elevation + slope 744 (100.0%), any OSM tag 288
(38.7%), shelter kind 225 (30.2%), display name 743 (99.9%). Overpass answered 504 on
both ingests and the retries recovered.

`pytest -m data` was not run against this database.

## How the 2026-10-13 snapshot was checked

1. `make dump` wrote `dumps/campsite-2026-10-13.dump`. From TM05-90 it also excludes the
   data of every `planning_*` table (waypoints, trip plans, plan stops, saved trails),
   which it did not before.
2. **No user data.** The dump's table of contents has no data entry for `auth_user`,
   `auth_user_groups`, `auth_user_user_permissions`, `authtoken_token`, `django_session`,
   `django_admin_log`, or any `accounts_*` or `planning_*` table.
3. **It restores.** It was restored with `--exit-on-error` into a throwaway database,
   `campsite_tm0590_verify`, separate from the dev database. The restore exited 0, all
   twelve of those tables held 0 rows, and the row counts matched the table above,
   including facts for all 756 White Mountains campsites. The throwaway was then dropped.
