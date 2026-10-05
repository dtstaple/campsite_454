# CampSite developer commands (TM05-67). Works with the GNU Make 3.81 that ships with macOS
# and with any Linux/WSL make. The one setup guide is docs/setup.md.
#
#   make setup     venv + Python deps, npm ci, .env, database container, migrations
#   make doctor    check everything, with a FIX line for each failure
#   make restore DUMP=<path-or-url>   load a database dump (fast data path)
#   make data      rebuild all Adirondacks data from the sources (slow data path)
#   make dev       run the backend (:8000) and frontend (:5173) together
#   make dump      write a dump of your database to dumps/

# .env supplies POSTGRES_*, DB_CONTAINER_NAME and COMPOSE_PROJECT_NAME. Missing on the
# first `make setup`, which creates it.
-include .env
export COMPOSE_PROJECT_NAME

VENV := .venv
VPY := $(VENV)/bin/python
DB_CONTAINER_NAME ?= campsite_db
POSTGRES_USER ?= campsite
POSTGRES_DB ?= campsite
REGION ?= adirondacks
STEPS ?=
DUMP ?=
# The current team snapshot (GitHub Release). Update it when a new snapshot is published.
SNAPSHOT_URL := https://github.com/dtstaple/campsite_454/releases/download/dev-data-2026-10-05/campsite-2026-10-05.dump
OUT ?= dumps/campsite-$(shell date +%Y-%m-%d).dump

# Python 3.12 exactly: CI runs 3.12, and 3.13/3.14 have no wheels for some pinned deps.
PYTHON312 := $(shell command -v python3.12 2>/dev/null)

# Data that belongs to a person, not the project: dumped as empty tables.
# 'accounts_*' is a pattern, so a new per-user table in accounts/ is left out automatically.
PERSONAL_TABLES := auth_user auth_user_groups auth_user_user_permissions authtoken_token \
	'accounts_*' django_session django_admin_log

.PHONY: help setup doctor dev backend frontend data restore dump

help:
	@sed -n '4,10p' Makefile | sed 's/^# //'

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
	@echo "==> Database container"
	docker compose up -d --wait
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

backend:
	$(VPY) backend/manage.py runserver

frontend:
	cd frontend && npm run dev

data:
	$(VPY) scripts/build_data.py --region $(REGION) $(if $(STEPS),--only $(STEPS))

dump:
	@mkdir -p $(dir $(OUT))
	docker exec $(DB_CONTAINER_NAME) pg_dump -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		--format=custom --no-owner --schema=public \
		$(foreach t,$(PERSONAL_TABLES),--exclude-table-data=$(t)) > $(OUT)
	@ls -lh $(OUT)
	@echo "Dump written (accounts, tokens, sessions and saved campsites left out)."

# The dump's own `public` schema entry is skipped: PostGIS lives in that schema, so
# --clean could never drop it, and the schema already exists in every database here.
restore:
	@if [ -z "$(DUMP)" ]; then \
		echo "Usage: make restore DUMP=<path-or-url>"; \
		echo "  latest team snapshot: make restore DUMP=$(SNAPSHOT_URL)"; \
		exit 1; fi
	@file="$(DUMP)"; \
	case "$$file" in http://*|https://*) \
		mkdir -p dumps; file="dumps/$$(basename "$$file")"; \
		echo "==> Downloading $(DUMP)"; curl -fL --progress-bar -o "$$file" "$(DUMP)" || exit 1;; \
	esac; \
	echo "==> Restoring $$file into $(DB_CONTAINER_NAME) (replaces existing data and local accounts)"; \
	docker cp "$$file" $(DB_CONTAINER_NAME):/tmp/restore.dump || exit 1; \
	docker exec $(DB_CONTAINER_NAME) sh -c '\
		pg_restore -l /tmp/restore.dump | grep -v -e " SCHEMA - public " -e " COMMENT - SCHEMA public " > /tmp/restore.list && \
		pg_restore -U $(POSTGRES_USER) -d $(POSTGRES_DB) --clean --if-exists --no-owner \
			--exit-on-error -L /tmp/restore.list /tmp/restore.dump; \
		status=$$?; rm -f /tmp/restore.dump /tmp/restore.list; exit $$status'
	$(VPY) backend/manage.py migrate --no-input
	@echo "Restored. Accounts are not in dumps: make an admin with"
	@echo "  $(VPY) backend/manage.py createsuperuser"
