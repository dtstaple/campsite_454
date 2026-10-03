# CLAUDE.md — CampSite (Team 5, CIS454)

The shared rules for this repo, read automatically by Claude Code. Everyone on the team
works from this file. Put personal notes and preferences in `CLAUDE.local.md`, which is
gitignored and loaded alongside this one.

The course autograder reads Jira and Git directly. The Jira and Git conventions below are
graded, so they are rules, not style preferences.

## 1. The project

CampSite finds and scores backcountry campsites with real geospatial analysis. A weighted
model scores each candidate site 0–100 on:

- distance to water
- terrain slope
- trail access
- land cover
- legal camping status
- seasonal weather

**The score must stay explainable, factor by factor.** That is why it is a transparent
weighted model, not a learned one.

- Repo: `dtstaple/campsite_454`
- Jira space key: `TM05`
- Setup, for every OS: **`docs/setup.md`**, the one setup guide.

| Name | Owns |
|---|---|
| Davis Stapleton | Data pipeline, architecture, PostGIS schema, spatial API |
| Bleron Balidemaj | Docker, database infrastructure, deployment config |
| Abdulrahman Shaalan | Django backend, auth, API endpoints |
| Sahaj Soni | React frontend, MapLibre map |

Use these exact full names anywhere in Jira. The grader string-matches them.

## 2. Stack and layout

- **Backend.** Python 3.12 (`.python-version`; 3.13/3.14 break some wheels), Django,
  DRF, `django.contrib.gis`.
- **Database.** PostgreSQL 16 + PostGIS 3.4 in Docker, container `campsite_db`.
- **Frontend.** React + TypeScript + Vite, with MapLibre GL (not Mapbox). Node 20
  (`.nvmrc`), the same as CI.
- **Tooling.** ruff for lint and format; pytest with coverage; oxlint for the frontend.
  GitHub Actions runs all of them on every push and PR.

```
backend/            Django project (config/, api/, accounts/, ...)
backend/pipeline/   ingestion framework, source adapters, regions.yml
backend/geodata/    PostGIS models for ingested vector data
backend/analysis/   on-demand raster analyses + their cache (3DEP, weather, ...)
backend/enrichment/ derived per-campsite facts
frontend/           React + Vite + MapLibre
tests/              pytest suite, shared fixtures in conftest.py
docs/               documentation (graded evidence)
artifacts/          non-code evidence (screenshots, exports, run reports)
scripts/            developer tooling behind the Makefile
Makefile            setup / doctor / dev / data / restore / dump
```

## 3. Git

- **Branch:** `TM05-<issue>-short-description`, from an up-to-date `main`.
- **Every commit message starts with the issue key**, or Jira does not link it:

  ```
  TM05-13 add OSM trail adapter with node ID preservation
  ```

- **Flow.** Commit small and often, open a PR to `main`, and merge only when CI is green.
- **Each person commits their own work.** Commits are authored by whoever did the work,
  under their own Git identity, on their own story. Don't commit a teammate's work as
  yourself, or yours as them. Contribution is graded from the Git history.
- **Stage explicit paths.** Use `git add <paths>`, not `git add .`, so local files never
  slip in.

## 4. The gate: run it before every commit

```
ruff check . && ruff format --check . && pytest
cd frontend && npm run lint && npm run build
```

If any of it fails, don't commit. If CI is red, the story is not done.

- Never weaken a test or lower a threshold to get green; fix the code.
- Write tests alongside the code.

## 5. Secrets

**Never commit** `.env`, API keys (RIDB, Stadia, anything), credentials, database dumps or
`CLAUDE.local.md`.

- `.env.example` holds placeholder values only. Every variable the app reads is listed
  there with an explanation.
- Dumps are shared as GitHub Release assets, never committed (`dumps/` is gitignored).

## 6. Code conventions

The full standard is in `docs/coding-conventions.md`. The ones that bite:

- **Frontend colours, spacing, radii and shadows come only from `frontend/src/theme.css`
  tokens.** Use the CSS custom properties, read in TypeScript through `theme.ts`, and never
  hard-code a hex value or pixel shadow in a component or map layer. A new look means a new
  token.
- **`maplibre-gl.css` is imported exactly once**, in `frontend/src/main.tsx`, and
  `vite.config.ts` keeps `optimizeDeps.exclude: ['maplibre-gl']`.
- **Metres, never degrees.** Geometry is stored in EPSG:4326, so the `.length`, `.area` and
  `ST_Distance` of a `geom` are in *degrees*, which is wrong and varies with latitude.
  - Measure on `geom_m` (EPSG:5070, `METRIC_SRID`) or on `geography`.
  - Put the unit in the name: `distance_m`, `length_km`, `radius_mi`.
- **Keep the score explainable.** Every factor is visible and documented in
  `docs/scoring.md`.
- **Delete dead code** rather than leaving it.

## 7. Data pipeline

The central rule: **store derived results, not raw sources.**

- **Vector reference data is fetched once and persisted.** That covers RIDB, OSM
  trails/campsites/routes, NHD water and PAD-US land.
- **Raster and imagery data** (3DEP, Sentinel-2, soils) is read on demand for a specific
  area. Only the *answer* is cached, with provenance, in `analysis`. **The pixels are
  discarded.**
- **Weather** is live, with a short cache, and never persisted.

Every source adapter implements `fetch(aoi)`, then `normalize(raw)`, then `load(records)`.

- Geometry is stored as SRID 4326, with a spatial index on every geometry column.
- `load()` is idempotent: it upserts by a stable source ID.
- Areas of interest come from `backend/pipeline/regions.yml`, never a hardcoded bbox.
- Every run writes an `IngestRun` provenance record.
- A new source is one new adapter. Shared concerns live in the framework.

### Running ingests

```
make data                              # the full Adirondacks rebuild, timed per step
make data STEPS=padus,osm-routes       # part of it
make data REGION=white-mountains-nh    # another region from regions.yml
.venv/bin/python backend/manage.py ingest <source> <region>   # one source directly
```

- Sources: `padus`, `nhd-flowlines`, `nhd-waterbodies`, `osm-trails`, `osm-campsites`,
  `ridb` (needs `RIDB_API_KEY`), and `osm-routes`.
- After the ingests come `build_route_profiles <region>` and then
  `enrich_campsites <region>`.
- To skip all of it, use `make restore DUMP=<url>`.
- After any ingest, run `pytest -m data`.

## 8. Jira (graded; follow exactly)

**Every story needs four things:**

- an assignee
- a description
- **Acceptance Criteria in the dedicated AC field**
- Fibonacci story points: 1, 2, 3, 5, 8 or 13

Read a story's AC before building it; the AC is the definition of done. If the scope
changes, update the AC first.

**Workflow.** Stories go `To Do → In Progress → Done`.

- Never skip In Progress.
- A story stays In Progress for at least 5 real minutes.
- Done means finished and merged.

**Worklogs.** Log time on the story you actually worked on.

- Each entry needs a specific description of what was done, plus a link to the commit,
  PR, or `/docs` or `/artifacts` file. "Worked on story" scores zero.
- Aim for about 4 hours per person per sprint.

**Sprint Report.** Each sprint has a `Sprint N Report` story with exactly four subtasks:
`SCRUM 1`, `SCRUM 2`, `Sprint Review` and `Retrospective`.

- All four are Done before the parent closes, and the report never rolls over.
- Use real Jira tables, never screenshots.
- Attendance is listed by full name.
- Table headers are string-matched:

  ```
  | Team Member | Have Done | Plan To Do | Roadblocks |
  | Team Member | Went Well? | Could be Better? | How could be fixed? | Specific Actions |
  ```

**Rollovers** need a comment giving the current state, the blocker and the next step.

**Sprints** run Tuesday to Tuesday, closing by 23:59 ET.

`TM05-2` (the Scrum Master schedule) stays in the backlog permanently and is never added to
a sprint.
