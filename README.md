# CampSite

Finds and scores backcountry campsites with real geospatial analysis. A transparent
weighted model scores each candidate site 0–100 on water proximity, slope, trail access,
land cover, legal status and weather, and shows the score factor by factor. CIS454, Team 5.

**Stack:** Django + DRF + GeoDjango, PostgreSQL 16 + PostGIS 3.4 (Docker), React + Vite +
MapLibre.

## Get running

```
make setup
make restore DUMP=<dump URL>   # or: make data (full rebuild), or the sample
make doctor
make dev                        # http://localhost:5173
```

Prerequisites per OS, the data options, and troubleshooting are in
**[docs/setup.md](docs/setup.md)**, the one setup guide.

## More

| Doc | What |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Team rules: Jira, Git, the gate, conventions |
| [docs/onboarding.md](docs/onboarding.md) | New-teammate orientation |
| [docs/architecture.md](docs/architecture.md) | Architecture and the pipeline design |
| [docs/pipeline.md](docs/pipeline.md) | Ingest sources and regions |
| [docs/scoring.md](docs/scoring.md) | The scoring model |
| [docs/api.md](docs/api.md) | API endpoints |
