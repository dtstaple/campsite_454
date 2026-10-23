# Run report: Sprint 7, Davis Stapleton's stories (2026-10-23)

This report covers an unattended run of TM05-128, TM05-118 and TM05-119, in that order,
each on its own branch from an up-to-date `main`, merged only when CI was green. Every AC
item below is marked met or not met, with its evidence. Judgment calls are listed per
story, as is every edit to a file teammates have also worked on. No worklogs were
created, and no story was moved to Done.

| Story | PR | Merge | Jira |
|---|---|---|---|
| TM05-128 Fix failing checks on main | [#100](https://github.com/dtstaple/campsite_454/pull/100), merged before this run | Merged (`33f0acb`) | Confirmation comment |
| TM05-118 Per-region camping rules | [#101](https://github.com/dtstaple/campsite_454/pull/101) | Merged (`76584f0`) | Comment with PR and summary |
| TM05-119 Plan trips across connected trails | [#102](https://github.com/dtstaple/campsite_454/pull/102) | Merged (`896610e`) | Comment with PR and summary |

## Baseline (main `33f0acb`, before any change)

- **`make doctor`:** all checks passed.
- **Gate:**
  - ruff check and ruff format --check: pass (215 files)
  - makemigrations --check: no changes
  - pytest: 1004 passed, coverage 94.74% (floor 93%)
  - frontend npm ci, lint, build, test: pass. Lint has 1 pre-existing warning (`src/session.tsx:41`); tests 157/157.
- **Local data:** the dev database had no White Mountains campsite facts. I ran
  `enrich_campsites white-mountains-nh` (756 sites, local only) before taking the
  verdict baseline, so that baseline would mean something. Doing so changed no
  Adirondacks verdict: all 743 were identical before and after.

## TM05-128: Fix failing checks on main

Its fix had already merged in PR #100 (2026-10-21). This run re-checked it.

| AC | Met | Evidence |
|---|---|---|
| Every local check passes | Yes | The baseline gate above, run on `33f0acb` |
| Main CI passes | Yes | `gh run list --branch main`: the #100 merge run succeeded |
| No behaviour changes beyond the fixes | Yes | PR #100 changed only `scripts/doctor.py` and its tests |

## TM05-118: Per-region camping rules

**What changed:**
- **`backend/scoring/legality.yml` (new):** each region's area, authority, designation
  evidence and rules, each quoted from an official source.
- **`backend/scoring/rules.py` (new):** loads and validates the file.
- **`backend/scoring/verdict.py`:** now applies the region's rules.
- **`backend/planning/candidates.py`, `plans.py` (minimal):** computed candidates cite
  their own region's rule.
- **Rule kinds:** `max_elevation`, `no_camping`, `setback` and `undesignated`. Every number
  carries its unit, and nothing in the format is US-only.

| AC | Met | Evidence |
|---|---|---|
| Rules live in per-region config, not code | Yes | `legality.yml`. `test_a_new_region_needs_only_a_config_entry` adds a metres-based region by config alone |
| Adirondacks: DEC rules, unchanged in behaviour | Yes | All 743 dev-DB verdicts byte-identical (verdict, label, reason, rule, designation basis), including a 50-site random sample (seed 118). `test_adirondack_verdicts_are_identical_to_before_tm05_118` replays 1,920 inputs against outputs frozen from the old code (`tests/fixtures/adirondack_verdicts_pre_tm05_118.json`) |
| White Mountains: National Forest rules, each cited | Yes | Quoted from the [WMNF Backcountry Camping Regulations and Guide](https://www.fs.usda.gov/sites/nfs/files/r09/whitemountain/publication/Backcountry%20Camping%20Regulations%20%26%20Guide%20%28Web%20Version%29.pdf): closed areas, the wilderness trail setbacks, the FPA trails and waters, the 1/4 mile developed-sites FPA, and partner-run sites. The alpine zone, the Cutler River Drainage and the partial-segment rules are cited and listed as `unchecked` |
| No-rules region: "Unknown: check current rules", never "Permitted" | Yes | Tested for the Green Mountains and for outside every region, across designated, lean-to and plain sites and every land status |
| Tests for each region and the fallback | Yes | `tests/test_legality_rules.py`: 52 tests |
| `docs/scoring.md` documents the format | Yes | "Per-region camping rules (TM05-118)" |

**Verdict counts** (dev DB, 1,500 sites):

| Region | Verdict | Before | After |
|---|---|---|---|
| Adirondacks | Permitted · designated site | 308 | 308 |
| | Not permitted | 3 | 3 |
| | Unknown: check current rules | 432 | 432 |
| White Mountains | Permitted · designated site | 660 | 664 |
| | Not permitted | 3 | 3 |
| | Unknown: check current rules | 93 | 89 |
| Outside every region | Unknown | 1 | 1 |

- **White Mountains, 4 newly Permitted:** all four are AMC-run sites.
- **The 89 Unknown** now cite Forest Service rules where they used to cite DEC's 150 ft
  rule:
  - 85 the 1/4 mile developed-sites FPA
  - 3 a wilderness trail setback
  - 1 Unknown Pond
- **No site became Not permitted from a new rule.**

**Judgment calls:**
- **Setbacks give Unknown, never Not permitted.** They hold "except at designated sites",
  and designated sites in Wilderness "may not appear on any maps".
- **No treeline elevation is used.** No official source gives one; the Forest Service
  files that might have were maps with no text. The alpine-zone rule is cited but never
  decides a verdict.
- **The White Mountains area is the region's ingestion box.** Rules there can only make
  a verdict more cautious.
- **The PAD-US land gate (`legal_status`) stays in `scoring/config.yml`.** It is the
  score's legal factor and already config-driven; moving it would change scores.
- **No-rules regions report Unknown even on closed land.** I read "always Unknown"
  literally. The reason still says the land is marked closed.
- **The docs commit was not re-gated.** The gate ran once on the full tree; the docs
  commit changed no code.

**Edits to files teammates also work on:** `backend/planning/plans.py` (Sahaj Soni has one
commit there): `_candidate_legality` now takes the site, to cite its region's rule.

## TM05-119: Plan trips across connected trails

**What changed:**
- **The `routing` app:**
  - `engine.py`: the replaceable engine
  - `build.py` with `build_trail_graph`
  - `models.py`: `TrailEdge`, `TrailGraphBuild`
  - `service.py`: snapping, route ids, assembly
  - views and urls
- **Planning:** `TripPlan.planned_route`, through migration `planning.0006`.
- **Frontend:** `frontend/src/routing/` (planner, pure helpers, CSS), wired into
  `TrailInsight`.
- **Docs:** `docs/routing.md`, and "Planned routes" in `docs/api.md`.

| AC | Met | Evidence |
|---|---|---|
| Routable graph from shared junction nodes | Yes | Adirondacks: 29,077 edges and 30,854 nodes from 18,067 ways. `test_the_graph_has_one_edge_per_stretch_between_junctions` |
| User picks start, end and waypoints and gets a route across connected trails | Yes | In the browser at both sizes: four clicks gave Loj → Marcy → Phelps Mountain → Loj, a 3-leg loop over 8 named trails. `*-2-planner-stops.png`, `*-3-route-profile.png` |
| Total distance, gain and loss, profile, trails used | Yes | Panel: 17.5 mi, +4,727 ft / -4,734 ft, Loop, ≈ 8 h 5 min, the profile, "Trails on this route", and legs |
| Campsites along it work like a single trail, including + Night and GPX | Yes | Find campsites: 8 mapped and 8 potential. Two lean-tos as nights with daily distances (2.7 mi, 0.3 mi, 14.6 mi). GPX: 2,106 track points, 8 waypoints (`desktop-route.gpx`). Plans save by route id (`test_nights_on_a_planned_route_work_like_a_trail`) |
| Routing time for a typical trip, measured and documented | Yes | Below, and `docs/routing.md`, "Measured" |
| Tests: single-trail, multi-trail, unreachable | Yes | Plus waypoint order, Naismith vs distance, isolated-path snapping, re-solving by id, the API, and plans and GPX. `tests/test_routing.py` (21 tests) and `tests/test_routing_engine.py` (11) |

**Graph build** (`build_trail_graph adirondacks`): 1,220.7 s in total, of which 3DEP took
1,205.0 s. It drew 267,998 samples with 0 no-data values. Two transient 3DEP 502s were
retried and succeeded.

**Routing timings**, by Naismith time:
- **Cold:** a fresh process, which loads the graph.
- **Warm:** median of five runs.
- **Detail:** the full trail-panel payload. Its first call fetches the 3DEP profile.

| Trip | Distance | Climb (graph) | Naismith | Cold | Warm | Detail, first / cached |
|---|---|---|---|---|---|---|
| Adirondak Loj → Mount Marcy → Phelps Mountain → Loj | 25.4 km | 1,570 m | 7.7 h | 473 ms | 106 ms | 6.4 s / 0.32 s |
| Loj → Algonquin Peak → Lake Colden → Loj | 20.4 km | 1,228 m | 6.1 h | 292 ms | 108 ms | 3.9 s / 0.23 s |
| Upper Works → Lake Colden → Mount Marcy → The Garden | 34.8 km | 1,563 m | 9.6 h | 277 ms | 110 ms | 9.8 s / 0.82 s |

- **The A* search itself is under 1 ms.**
- **A cold request spends about 0.19 s loading the graph.**
- **The warm time is snapping queries** (about 70 ms) and line assembly (about 27 ms).

**Judgment calls:**
- **Snapping chooses one connected piece of the network.** The first timing run failed at
  the Loj: the nearest paths are a 13-node footway cluster that joins nothing, out of
  5,274 pieces. Snapping now picks the piece every click reaches within 400 m. There is a
  test for it.
- **Edge climb is the plain sum of 50 m rises.** It runs 8–12% above the profile's
  smoothed gain. The panel shows the profile's numbers, as for any trail.
- **Route identity is a re-solvable id** (`<region>:<cost>:<osm node ids>`), not a stored
  row. OSM node ids survive a rebuild.
- **Saved trails and hikes keep a trail by route or way only,** so for planned routes the
  panel hides Save trail and Start hike. Plans, the GPX and Find campsites work.
- **A route that walks a stretch twice has ambiguous miles there.** Sites locate on the
  first pass. Documented.
- **The planner reuses the waypoint tool's click flag** (`placement.active`), so a
  planner click never opens a trail or a popup.
- **After routing, the planner folds** to an "Edit route" button that keeps the stops.
  On a phone it sits above the location buttons and shows a stop count with "Undo last"
  instead of the list. The first phone check found it overlapping those buttons, and
  that's fixed.
- **Remount fix.** `TrailInsight` returned a different element tree with and without an
  open trail, which remounted the trail search and the planner whenever a trail opened.
  It now keeps them in one place.
- **Only the Adirondacks graph was built.** A White Mountains graph needs another 3DEP
  run of about 10 minutes; until then, planning there answers "No trail graph has been
  built for white-mountains-nh yet."
- **The browser checks used throwaway tooling outside the repo.** `playwright-core` was
  installed in a scratch folder (Playwright belongs to the backlog story TM05-136), and
  headless Chrome used SwiftShader for WebGL. A local-only `sprint7-demo` user signed in
  for + Night.

**Edits to files teammates also work on** (all minimal):

| File | Also touched by | Edit |
|---|---|---|
| `backend/config/settings.py` | Bleron Balidemaj, Abdulrahman Shaalan | `"routing"` added to `INSTALLED_APPS` |
| `backend/config/urls.py` | Abdulrahman Shaalan | `include("routing.urls")` |
| `pyproject.toml` | Bleron Balidemaj, Abdulrahman Shaalan | `routing` added to ruff's first-party list |
| `frontend/src/trails/TrailInsight.tsx` | Sahaj Soni | the planned selection kind, the planner mount, the remount fix, and Start hike hidden for planned routes |
| `frontend/src/trails/TrailPanel.tsx` | Sahaj Soni | the "Trails on this route" section |
| `frontend/src/trails/api.ts` | Sahaj Soni, Abdulrahman Shaalan | `planRoute` and `fetchPlannedRoute`, plus the `planned` field |
| `frontend/src/theme.css` | Sahaj Soni | new route-planner tokens only |

The protected areas were not touched: TM05-120, TM05-121, TM05-122, `backend/accounts/`
and TM05-130 to TM05-136. The routing views read `accounts.authentication` and
`accounts.weights`, as other views do.

## The routing interface to implement in C++

The full spec is in `docs/routing.md`, "The engine interface". In short:

```
graph:
  nodes  id:int64 -> (x, y) metres (EPSG:5070)
  edges  id:int64, u:int64, v:int64, length_m:float64,
         ascent_m:float64 (u->v climb), descent_m:float64
         undirected for walking; backwards swaps ascent and descent;
         negative node ids are per-request stops between junctions

route(graph, start, end, waypoints[], cost: "naismith" | "distance") -> Route
  naismith: length_m / (5000/3600) + 6 * ascent_m   seconds (descent free)
  distance: length_m
  legs solved independently, visiting waypoints in the order given (out-and-back allowed)
  must return the true least-cost path; costs equal to 1e-6

Route { cost, legs: [Leg], expanded }
Leg   { start, end, steps: [Step] }
Step  { edge, forward, from_node, to_node, length_m, ascent_m, descent_m }  (as walked)

errors: RoutingError (unknown node or cost), NoRoute(start, end) (not connected)
```

- **Where it plugs in:** the Python side calls it in one place,
  `routing/service.py::_solve`.
- **What it gets:** the graph rows from `EDGES_SQL` (an edge plus its endpoint
  coordinates).
- **What it must pass:** the cases in `tests/test_routing_engine.py`.

## What to check by hand in the browser

1. **On a real iPhone and Android phone** (`make dev-phone`, or the deployed URL once the
   routing graph is built there):
   - tap a start, two stops and an end
   - check the planner stays clear of the notch, the location buttons and the sheet
   - check "Edit route" is reachable when the sheet is at peek
2. **Edit route:** after a route opens, press it, add a stop, re-route. The panel should
   update, and the old route should not linger.
3. **Shortest vs Quickest** on a route with a steep alternative (e.g. Loj → Marcy): the
   trails list should change where the climb differs.
4. **Save a plan on a planned route,** reopen it from Profile → Plans, and download its
   GPX in a GPS app.
5. **An out-and-back route** (start = end with one far stop): check the miles of campsites
   on the way back (the known limit above).
6. **The verdict panels** for Sno-bird, Boreas Ponds Lean-To, Liberty Springs Tentsite
   and Unknown Pond Campsite. They should read as in
   `artifacts/sprint7/*-verdict-*.png`: unchanged in the Adirondacks, rule-based in the
   White Mountains.
7. **A click on the map's edge**, more than 400 m from any trail, and two clicks on
   trails that don't connect. Both should give a readable message, not a stuck spinner.

## Gate on main after the merges

Run on `main` at `896610e`, after both merges:

- `make doctor`: all checks passed
- `ruff check`: pass. `ruff format --check`: pass (233 files)
- `makemigrations --check`: no changes
- `pytest`: 1088 passed, 10 deselected, coverage 94.86% (baseline 1004 at 94.74%)
- frontend `npm ci`, lint, build, test: pass. Lint still has the 1 pre-existing warning;
  tests 164/164 (baseline 157).
- **Main CI** for the #102 merge: success. PR #101 and #102 were green before merging.
  One of #102's two `quality` runs took 17 min 20 s against the usual 3 min, but passed;
  the cause is not known (runner speed, probably, since no test touches the network).

## Screenshots and files

`artifacts/sprint7/`:
- `desktop-*` and `phone-*`, steps 1 to 5: map, planner stops, route and profile, Find
  campsites, two nights
- `*-verdict-*`: the four campsite verdict panels
- `desktop-route.gpx`
- `*-log.txt`: the checks' logs
