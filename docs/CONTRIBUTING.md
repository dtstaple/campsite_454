# Contributing

## Branch naming
`TM05-<issue number>-short-description`  (e.g. `TM05-9-docker-postgis`)

## Commit messages
Start every commit with the issue key so Jira links it automatically:

    TM05-9 add docker-compose with PostGIS 3.4

## Workflow
1. Branch from an up-to-date `main` using the pattern above
2. Commit small and often, always with the issue key
3. Open a PR back to `main` when ready
4. Move your Jira story To Do -> In Progress -> Done (never skip In Progress)
5. Log time in Jira with a real description plus a link to your commit or PR

## Before you push
Run the gate (also in `CLAUDE.md`; CI runs the same):

    ruff check . && ruff format --check . && pytest
    cd frontend && npm run lint && npm run build && npm test

Local setup is in `docs/setup.md`.

## Before you merge
`main` is protected by the `protect-main` ruleset: a PR cannot merge until both CI checks
pass.

- **`quality`** (Python): `ruff check`, `ruff format --check`, and `pytest` against a real
  PostGIS database, with branch coverage.
- **`frontend`**: `npm run lint` (oxlint), `npm run build` (the TypeScript type check plus
  the Vite build), and `npm test`.

**The coverage floor.** `pytest` fails if total coverage drops below `fail_under` in
`pyproject.toml` (`[tool.coverage.report]`), currently 93%. It was set 1 point below the
measured coverage (94.6%, line plus branch, on 2026-10-05). New code comes with tests.
Raise the floor when coverage goes up, and never lower it to get a PR green.

**Main is never merged red.** If a check fails, fix it on the branch and push again. Don't
merge "to fix later", and don't ask for the rule to be bypassed.
