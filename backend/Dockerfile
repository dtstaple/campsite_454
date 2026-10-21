# CampSite backend image (TM05-113). Build from the repo root:
#   docker build -f backend/Dockerfile -t campsite-backend .
# GDAL/GEOS come from the distribution's packages, the same recipe as CI
# (.github/workflows/ci.yml). Debian bookworm's GDAL 3.6 is in the range Django 5.1 probes
# for by name, so GDAL_LIBRARY_PATH and GEOS_LIBRARY_PATH stay unset.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      binutils libproj-dev gdal-bin libgdal-dev libgeos-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

WORKDIR /app
COPY backend/ /app/

# collectstatic only imports settings; these placeholders satisfy its required variables
# and never reach the running container.
RUN DATABASE_URL=postgis://build@localhost/build SECRET_KEY=build-only DEBUG=False \
    python manage.py collectstatic --no-input

RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app

# Render sets PORT (default 10000); 8000 locally. Migrations run on every start because the
# free tier has no pre-deploy step; on an up-to-date database they are a no-op. Two workers
# fit the free tier's 512 MB; the timeout covers the slowest on-demand terrain analyses.
ENV PORT=8000
EXPOSE 8000
CMD python manage.py migrate --no-input \
 && exec gunicorn config.wsgi:application --bind 0.0.0.0:$PORT \
      --workers ${WEB_CONCURRENCY:-2} --timeout 120 --access-logfile -
