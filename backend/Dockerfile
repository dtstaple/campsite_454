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

# Render sets PORT (default 10000); 8000 locally.
#
# Migrations (TM05-161): render.yaml runs them as the service's pre-deploy command, before the
# new image takes traffic, and sets MIGRATE_ON_START=False. Anywhere without a pre-deploy step
# (Render's free plan, `docker run`), the default runs them on every start instead; on an
# up-to-date database that is a no-op.
#
# Two workers fit 512 MB. GUNICORN_TIMEOUT (seconds) must cover the slowest on-demand request:
# a trail's first "Find campsites" samples 3DEP, normally 15-35 s, once 129 s on a busy machine
# (docs/candidates.md, docs/deployment.md).
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health/' % os.environ.get('PORT', '8000'), timeout=4)"
CMD if [ "${MIGRATE_ON_START:-True}" = "True" ]; then python manage.py migrate --no-input || exit 1; fi \
 && exec gunicorn config.wsgi:application --bind 0.0.0.0:$PORT \
      --workers ${WEB_CONCURRENCY:-2} --timeout ${GUNICORN_TIMEOUT:-180} --access-logfile -
