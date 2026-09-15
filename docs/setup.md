## Database (Docker + PostGIS)

Install Docker Desktop and make sure it's running. From the repo root, copy
`.env.example` to `.env` and set a local password. Then run `docker compose up -d`
to start PostgreSQL 16 with PostGIS 3.4. Verify it's working with
`docker compose exec db psql -U campsite -d campsite -c "SELECT postgis_version();"`.
Stop it with `docker compose down`; data persists in a named volume between restarts.
