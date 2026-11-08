# CampSite dev container: the app side (TM05-160). The database is the `db` service in
# docker-compose.yml next to this file. docs/setup.md, path A.
#
# Python 3.12 matches .python-version and CI. GDAL/GEOS/PROJ come from Debian's packages,
# the same recipe as CI and backend/Dockerfile: bookworm's GDAL 3.6 is a version Django 5.1
# finds by itself, so GDAL_LIBRARY_PATH stays unset. Node comes from the devcontainer
# feature in devcontainer.json.
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# The base image's Yarn apt source has an expired signing key, which fails apt-get update;
# the project uses npm, so that source is dropped first.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      binutils libproj-dev gdal-bin libgdal-dev libgeos-dev ca-certificates curl gnupg \
 && rm -rf /var/lib/apt/lists/*

# PostgreSQL 16 client tools from apt.postgresql.org: the team snapshot is a PG16 dump, and
# bookworm's own client (15) cannot read it. scripts/snapshot.py uses pg_restore from here.
# That repository also carries newer GDAL/GEOS/PROJ builds, so it is pinned below Debian's:
# only the client and libpq come from it, and GDAL stays the bookworm 3.6 that
# backend/Dockerfile (production) uses.
RUN install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && printf '%s\n' \
      'Package: *' 'Pin: origin apt.postgresql.org' 'Pin-Priority: 100' '' \
      'Package: postgresql-client-16 postgresql-client-common libpq5' \
      'Pin: origin apt.postgresql.org' 'Pin-Priority: 600' \
      > /etc/apt/preferences.d/pgdg \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/*

# Mount points for the named volumes that keep the container's .venv and node_modules apart
# from the host's (a macOS .venv or node_modules cannot run on Linux, and vice versa).
RUN mkdir -p /workspaces/campsite_454/.venv /workspaces/campsite_454/frontend/node_modules \
 && chown -R vscode:vscode /workspaces
