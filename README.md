# CampSite

Finds and scores backcountry campsites with real geospatial analysis. A transparent
weighted model scores each candidate site 0–100 on water proximity, slope, trail access,
land cover, legal status and weather, and shows the score factor by factor. CIS454, Team 5.

**Stack:** Django + DRF + GeoDjango, PostgreSQL 16 + PostGIS 3.4 (Docker), React + Vite +
MapLibre.

## Get running

```
make setup
make restore DUMP=https://github.com/dtstaple/campsite_454/releases/download/dev-data-2026-10-05/campsite-2026-10-05.dump
make doctor
make dev                        # http://localhost:5173
```

`make data` rebuilds from the sources instead, and a small sample is one command away.
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
