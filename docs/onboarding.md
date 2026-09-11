# Onboarding — CampSite (Team 5)

Everything you need to get running and find your work.

---

## 1. Install these (once per laptop)

| Tool | Link | Needed for |
|---|---|---|
| Git | https://git-scm.com/downloads | everyone |
| VS Code | https://code.visualstudio.com/ | everyone |
| Python 3.12 | https://python.org/ | backend, pipeline |
| Node.js 18+ | https://nodejs.org/ | frontend |
| Docker Desktop | https://www.docker.com/products/docker-desktop/ | database |

Verify:

    git --version
    python3 --version
    node -v
    docker --version

**VS Code extensions:** Python (Microsoft), ESLint, Prettier, Docker

---

## 2. Clone the repo

    git clone https://github.com/dtstaple/campsite_454.git
    cd campsite_454

---

## 3. Python setup (backend + pipeline people)

    python3 -m venv .venv
    source .venv/bin/activate       # Windows: .venv\Scripts\activate
    pip install -r requirements.txt

---

## 4. Your story and where your work goes

| Person | Jira story | Work in this folder |
|---|---|---|
| Davis Stapleton | **TM05-8** — Set up repo, CI, and testing framework | `/tests`, root config |
| Bleron Balidemaj | **TM05-9** — Set up local database with Docker (PostgreSQL + PostGIS) | repo root (`docker-compose.yml`) |
| Abdulrahman Shaalan | **TM05-10** — Set up backend server with a working test endpoint | `/backend` |
| Sahaj Soni | **TM05-11** — Set up frontend app with a working map on screen | `/frontend` |

Open your story in Jira and read its Acceptance Criteria — that's the definition of done.

---

## 5. How to work on your story

    # 1. Start from an up-to-date main
    git checkout main
    git pull

    # 2. Make your branch (use YOUR story number)
    git checkout -b TM05-9-docker-postgis

    # 3. Work, committing as you go — always start the message with your key
    git add .
    git commit -m "TM05-9 add docker-compose with PostGIS"

    # 4. Push and open a PR
    git push -u origin TM05-9-docker-postgis

Then open the pull request on GitHub, or from the Development panel inside your Jira story.

**Every branch name and commit message must start with your `TM05-<n>` key** — that's how Jira
links your work automatically, and it's part of how the class grades contributions.

---

## 6. Running tests

We have pytest + coverage + ruff set up. Before you push:

    source .venv/bin/activate
    ruff check .
    pytest

CI runs the same checks on every push and pull request. If CI is red, your story isn't done.

---

## 7. Jira habits (these are graded)

- Move your story **To Do → In Progress** when you start, **Done** only when it's actually finished
- Don't skip In Progress, and don't flip straight to Done
- **Log time** on your own story as you work, with a real description of what you did plus a link
  to your commit or PR
- Show up in both SCRUM tables with specific updates (not "worked on stuff")
- Aim for ~4 hours logged for the sprint

---

## 8. Add your run steps here when you're done

Once your piece works, add a short section below so the next person doesn't have to guess.

**Database (Bleron):** _add your steps_

**Backend (Abdulrahman):** _add your steps_

**Frontend (Sahaj):** _add your steps_
