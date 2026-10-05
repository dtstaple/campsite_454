# Onboarding — CampSite (Team 5)

Welcome. This page is orientation only. **Installing and running the project is in
[setup.md](setup.md)**, and that is the only place setup steps live.

## 1. Get running

Follow [setup.md](setup.md) for your OS. On a fresh clone that is:

    make setup
    make restore DUMP=<dump URL from the team channel>
    make doctor
    make dev

If `make doctor` shows a FAIL, apply its FIX line. If that doesn't make it obvious, paste
the output into Claude Code.

## 2. Tools

- **VS Code** with the Python, Ruff, oxc (we lint with oxlint, not ESLint), Docker and,
  on Windows, WSL extensions.
- **Claude Code** reads the committed [`CLAUDE.md`](../CLAUDE.md) automatically: the team's
  Jira, Git and code rules. Put personal notes in `CLAUDE.local.md`, which is gitignored.

## 3. Who owns what

| Name | Owns |
|---|---|
| Davis Stapleton | Data pipeline, architecture, PostGIS schema, spatial API |
| Bleron Balidemaj | Docker, database infrastructure, deployment config |
| Abdulrahman Shaalan | Django backend, auth, API endpoints |
| Sahaj Soni | React frontend, MapLibre map |

Your current story is on the Jira board, space `TM05`. Read its Acceptance Criteria first;
that is the definition of done.

## 4. Working on a story

    git checkout main && git pull
    git checkout -b TM05-<n>-short-description
    # work, and commit with the key first:
    git commit -m "TM05-<n> what changed"
    git push -u origin TM05-<n>-short-description

Open a PR to `main` and let CI go green. The full rules (the gate, Jira habits, worklogs,
the sprint report) are in [`CLAUDE.md`](../CLAUDE.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## 5. Where to read next

- [architecture.md](architecture.md): how the pieces fit together
- [pipeline.md](pipeline.md): the ingest sources
- [scoring.md](scoring.md): the score
- [api.md](api.md): the endpoints
