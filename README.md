# CampSite

Finds and scores backcountry campsites with real geospatial analysis. A transparent
weighted model scores each candidate site 0–100 on water proximity, slope, trail access,
land cover, legal status and weather, and shows the score factor by factor. CIS454, Team 5.

**Stack:** Django + DRF + GeoDjango, PostgreSQL 16 + PostGIS 3.4 (Docker), React + Vite +
MapLibre.

## Get running

With nothing installed: **Code → Codespaces → Create codespace on main**. The dev container
sets everything up and loads the data; then run `make dev`.

On your own machine, with Docker:

```
make setup
make restore DUMP=$(make -s snapshot-url)   # the latest team data snapshot
make doctor
make dev                                    # http://localhost:5173
```

The three setup paths (dev container, local Docker, hosted dev database), prerequisites per
OS, the data options, and troubleshooting are in **[docs/setup.md](docs/setup.md)**, the
one setup guide.

## More

| Doc | What |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Team rules: Jira, Git, the gate, conventions |
| [docs/onboarding.md](docs/onboarding.md) | New-teammate orientation |
| [docs/architecture.md](docs/architecture.md) | Architecture and the pipeline design |
| [docs/pipeline.md](docs/pipeline.md) | Ingest sources and regions |
| [docs/scoring.md](docs/scoring.md) | The scoring model |
| [docs/api.md](docs/api.md) | API endpoints |
