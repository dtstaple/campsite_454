# CampSite developer commands (TM05-67). Works with the GNU Make 3.81 that ships with macOS
# and with any Linux/WSL make. The one setup guide is docs/setup.md.
#
#   make setup     venv + Python deps, npm ci, .env, database container, migrations
#   make doctor    check everything, with a FIX line for each failure
#   make restore DUMP=<path-or-url>   load a dump (fast data path; FORCE=1 replaces data)
#   make data      rebuild all Adirondacks data from the sources (slow data path)
#   make refresh REGION=<region>   refresh one region, with record counts per step
#   make terrain REGION=<region>   terrain facts and zones with GeoLibre (resumable)
#   make dev       run the backend (:8000) and frontend (:5173) together
#   make dev-phone the same over HTTPS on the LAN, to test on a phone (TM05-103)
#   make prewarm   cache the campsite search for the demo trails (TRAILS="A,B")
#   make dump      write a dump of your database to dumps/

# Make reads only COMPOSE_PROJECT_NAME from .env (docker compose reads the rest itself, and
# the Python scripts and Django read .env on their own). Including the whole file would turn
# every line into a make variable that overrides the process environment for every command,
# so a host .env would beat the dev container's own DATABASE_URL and GDAL settings (TM05-160).
# .env is missing on the first `make setup`, which creates it.
ifneq ($(wildcard .env),)
COMPOSE_PROJECT_NAME ?= $(shell sed -n 's/^COMPOSE_PROJECT_NAME=//p' .env)
endif
ifneq ($(COMPOSE_PROJECT_NAME),)
export COMPOSE_PROJECT_NAME
endif

VENV := .venv
VPY := $(VENV)/bin/python
REGION ?= adirondacks
STEPS ?=
DUMP ?=
FORCE ?=
NO_TERRAIN ?=
# The current team snapshot (GitHub Release). Update it when a new snapshot is published.
SNAPSHOT_URL := https://github.com/dtstaple/campsite_454/releases/download/dev-data-2026-11-10/campsite-2026-11-10.dump
OUT ?= dumps/campsite-$(shell date +%Y-%m-%d).dump

# Python 3.12 exactly: CI runs 3.12, and 3.13/3.14 have no wheels for some pinned deps.
PYTHON312 := $(shell command -v python3.12 2>/dev/null)

.PHONY: help setup doctor dev backend frontend data refresh terrain restore dump dev-phone prewarm \
	snapshot-url

help:
	@sed -n '4,13p' Makefile | sed 's/^# //'

setup:
	@if [ -z "$(PYTHON312)" ]; then \
		echo "FAIL python3.12 not found."; \
		echo "     FIX: macOS: brew install python@3.12   Ubuntu/WSL: sudo apt install python3.12 python3.12-venv"; \
		exit 1; fi
	@if [ -x $(VPY) ] && ! $(VPY) -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))'; then \
		echo "FAIL .venv exists but is not Python 3.12."; \
		echo "     FIX: rm -rf .venv && make setup"; exit 1; fi
	@echo "==> Python virtualenv ($(PYTHON312))"
	@[ -x $(VPY) ] || $(PYTHON312) -m venv $(VENV)
	$(VPY) -m pip install --quiet --upgrade pip
	$(VPY) -m pip install --quiet -r requirements.txt
	@echo "==> Frontend packages"
	cd frontend && npm ci --no-audit --no-fund
	@echo "==> .env"
	@$(PYTHON312) scripts/ensure_env.py
	@# TM05-160: Docker Compose only on the local Docker path. The dev container has its own
	@# db service, and a hosted DATABASE_URL needs no container (scripts/db_path.py).
	@path=$$($(PYTHON312) scripts/db_path.py); \
	if [ "$$path" = docker ]; then echo "==> Database container"; docker compose up -d --wait; \
	else echo "==> Database: the $$path path, so no local container is started"; fi
	@echo "==> Migrations"
	$(VPY) backend/manage.py migrate --no-input
	@echo
	@echo "Setup done. Next: get data, then make doctor and make dev. Fastest:"
	@echo "  make restore DUMP=$(SNAPSHOT_URL)"

doctor:
	@if [ -x $(VPY) ]; then $(VPY) scripts/doctor.py; else python3 scripts/doctor.py; fi

dev:
	@echo "Backend:  $(VPY) backend/manage.py runserver        -> http://localhost:8000"
	@echo "Frontend: cd frontend && npm run dev               -> http://localhost:5173"
	@echo "Running both; Ctrl-C stops both."
	@trap 'kill 0' INT TERM; \
		$(VPY) backend/manage.py runserver & \
		(cd frontend && npm run dev) & \
		wait

# TM05-103: the app on a real phone over HTTPS (geolocation needs it). Vite serves HTTPS
# on the LAN with a self-signed certificate and proxies /api to Django, which stays on
# this machine. DEV_LAN_ORIGIN lets Django's dev settings trust that origin.
# docs/setup.md, "Testing on a phone".
LAN_IP ?= $(shell ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | cut -d' ' -f1)

dev-phone:
	@if [ -z "$(LAN_IP)" ]; then echo "Couldn't find this machine's LAN address; run make dev-phone LAN_IP=192.168.x.y"; exit 1; fi
	@echo "On the phone (same Wi-Fi): https://$(LAN_IP):5173/discover"
	@echo "Accept the certificate warning once: it is this machine's own self-signed one."
	@echo "Running both; Ctrl-C stops both."
	@trap 'kill 0' INT TERM; \
		DEV_LAN_ORIGIN=https://$(LAN_IP):5173 $(VPY) backend/manage.py runserver 127.0.0.1:8000 & \
		(cd frontend && PHONE=1 VITE_API_BASE_URL= npm run dev) & \
		wait

# TM05-104: run and cache "Find campsites along this trail" (and the elevation profile)
# for the trails a demo will open, so the first click is instant. Comma-separated names;
# prints the time each took. docs/setup.md, "Before a demo".
DEMO_TRAILS = Van Hoevenberg,Phelps Trail,Deer Pond Trail,Cheney Pond-Irishtown
TRAILS ?= $(DEMO_TRAILS)

prewarm:
	$(VPY) backend/manage.py prewarm_candidates "$(TRAILS)"

backend:
	$(VPY) backend/manage.py runserver

frontend:
	cd frontend && npm run dev

data:
	$(VPY) scripts/build_data.py --region $(REGION) $(if $(STEPS),--only $(STEPS))

# TM05-91: every ingest source, then route profiles, then enrichment, for one region.
# Stops at the first failure and prints time and IngestRun record counts per step.
refresh:
	$(VPY) backend/manage.py refresh $(REGION)

# TM05-141: GeoLibre terrain facts per campsite and zone polygons, over 3DEP. The DEM and
# runtime are cached outside git (TERRAIN_CACHE_DIR); finished tiles are reused.
terrain:
	$(VPY) backend/manage.py terrain $(REGION)

# TM05-160: dump and restore go through scripts/snapshot.py, against whatever DATABASE_URL
# points at: the local Docker database, the dev container's db service, or a hosted PostGIS.
# A dump leaves out every person's data and checks that it did. A restore refuses a database
# that already has data unless FORCE=1, creates PostGIS if it is missing, then migrates.
dump:
	$(VPY) scripts/snapshot.py dump --out $(OUT)

restore:
	@if [ -z "$(DUMP)" ]; then \
		echo "Usage: make restore DUMP=<path-or-url> [FORCE=1] [NO_TERRAIN=1]"; \
		echo "  latest team snapshot: make restore DUMP=$(SNAPSHOT_URL)"; \
		exit 1; fi
	$(VPY) scripts/snapshot.py restore "$(DUMP)" $(if $(FORCE),--force) $(if $(NO_TERRAIN),--no-terrain)

snapshot-url:
	@echo $(SNAPSHOT_URL)
