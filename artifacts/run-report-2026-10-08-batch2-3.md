# Run report: Sprint 5, batches 2 and 3 (2026-10-08)

This was an unattended run over ten stories, in this order:
1. TM05-76 follow-up
2. the trail-panel bug (TM05-97)
3. TM05-74
4. TM05-85
5. TM05-79
6. TM05-80
7. TM05-81
8. TM05-83
9. TM05-78
10. TM05-84

**Every story merged** to `main` with a merge commit after green CI, and none needed a CI fix attempt. Each branch was cut from an up-to-date `main`. Jira has a comment with the PR link and a summary on each story. No story was moved to Done, and no worklogs were created. Nothing was pushed to `main` directly, nothing was force-pushed, and no Docker volume or system prune was run.

**`make doctor`**: all checks passed. The one warning is the existing `.env` SECRET_KEY dev fallback. Data counts: Campsite 1,500, Trail 25,663, TrailRoute 452, AnalysisResult 1,958.

**Final gate on `main`**:
- **Backend:** `ruff check`, `ruff format --check`, and `pytest`, with 770 passed and coverage above the 93% floor.
- **Frontend:** `npm run lint` (only the 3 pre-existing warnings, in `session.tsx` and `Discover.tsx`), `npm run build`, and `npm test`, with 88 passed.

| # | Story | PR | Status |
|---|---|---|---|
| 0 | TM05-76 follow-up: legality verdict | [#64](https://github.com/dtstaple/campsite_454/pull/64) | merged |
| 0b | TM05-97 Trail panel for named non-route trails (the bug story) | [#63](https://github.com/dtstaple/campsite_454/pull/63) | merged |
| 1 | TM05-74 Trail search and Discover list | [#65](https://github.com/dtstaple/campsite_454/pull/65) | merged |
| 2 | TM05-85 Filter trails in Discover | [#66](https://github.com/dtstaple/campsite_454/pull/66) | merged |
| 3 | TM05-79 Export a trail as GPX | [#67](https://github.com/dtstaple/campsite_454/pull/67) | merged |
| 4 | TM05-80 Custom waypoints | [#68](https://github.com/dtstaple/campsite_454/pull/68) | merged |
| 5 | TM05-81 Plan overnight stops | [#69](https://github.com/dtstaple/campsite_454/pull/69) | merged |
| 6 | TM05-83 Contour lines | [#70](https://github.com/dtstaple/campsite_454/pull/70) | merged |
| 7 | TM05-78 Open the map at the user's location | [#71](https://github.com/dtstaple/campsite_454/pull/71) | merged |
| 8 | TM05-84 Slope-angle shading | [#72](https://github.com/dtstaple/campsite_454/pull/72) | merged |

**Rollover comment drafts: none.** Every story was finished and merged, including TM05-84, which the brief allowed to stay open.

---

## The trail-panel bug (TM05-97): root cause

**Symptom.** In Hiking mode, clicking the Adirondack Rail Trail opened the small segment popup instead of the trail panel.

**Causes ruled out:**
- **Click priority.** Route clicks are handled on `named-routes-hit`, and there was nothing in that layer under the click.
- **Zoom or visibility.** Routes load from zoom 9, the same zoom trail linework appears.

**Cause: route membership.** None of the Rail Trail's 55 OSM ways is a member of any ingested `TrailRoute`.
- `way/20074658` is `highway=path`. Its only relation is **1376439 "Adirondack Branch", which is `route=railway`**, the old rail line.
- The route ingest correctly keeps only `route=hiking`.
- Only route members opened the panel, so this trail never could.
- **This is the normal case, not an edge case:** 3,652 of the 4,494 named Adirondack trail ways (81%) belong to no `TrailRoute`. That is 2,153 names and about 3,760 km of trail.

**Fix.** `GET /api/trails/<way>/trail/` returns the way's route when it has one. Otherwise it assembles a trail from the connected ways with the same name.
- Ways connect through shared `osm_node_ids`, or ends within 15 m.
- A named segment's click opens the panel, labelled "Assembled from mapped segments".
- An unnamed segment keeps its popup.
- **Judgment call:** shared nodes alone left the Rail Trail in 19 pieces, because mappers stopped ways 4.7–12.7 m short at crossings. A 15 m same-name end join takes it to 7 pieces. The remaining 17, 23 and 189 m gaps stay split, because a wider join risks merging different trails.

---

## Per story

### 0. TM05-76 follow-up: legality verdict (PR #64, merged)

**AC:** met. The campsite panel shows "Permitted · designated site", "Not permitted" or "Unknown: check current rules" above the score. Each verdict has a reason and the NYS DEC rule it rests on, with the source cited in docs/scoring.md. Legality is removed from the factor list.

**Measurements (1,500 sites):**
- 968 Permitted, 526 Unknown, 6 Not permitted.
- 483 verdicts changed from the land-only gate.
- **Sno-bird** (`node/4252860218`, tagged as designated, at 4,028 ft) reads Unknown, citing the 4,000 ft rule.
- 354 designated sites carry the "near a trail is normal" note.

**Judgment calls:**
- A 50 ft margin around the elevation limits, to allow for 3DEP point error.
- A "designated" OSM tag counts as designation.
- At-large legality is Unknown, because roads aren't in the data, so the 150 ft rule can't be checked.

**Protected files:** none. Sahaj's `ScoreBreakdown` receives a copy of the score without the legal factor, and her code is untouched.

### 0b. TM05-97: trail panel for named non-route trails (PR #63, merged)

**AC:** met (root cause above).

**Measurements:** the Rail Trail's Lake Clear section has 7 ways and runs 20.8 km. The first profile took 17 s (3DEP); after that it takes 0.5–0.9 s from cache.

**Protected files:** none.

### 1. TM05-74: trail search and Discover list (PR #65, merged)

**AC:** met. Name search ignores case and accents and requires every word. The Discover list shows routes in or near the view, nearest first. Picking a result opens its panel. Empty states have their own wording.

**Measurements:** 70–150 ms warm, about 1.6 s for the first request in a process.

**Judgment calls:**
- Matching runs in Python on normalised names, avoiding an `unaccent` migration for 452 routes.
- The bbox is grown by 50% on every side, so the list covers routes "near" the view.

**Protected files:** none.

### 2. TM05-85: filter trails in Discover (PR #66, merged)

**AC:** met. Filters for length, gain, difficulty, route type and campsites-within combine with each other and with search, update the list live, and **Clear filters** resets them.

**Judgment calls:**
- Filter facts are **stored** (the `RouteFacts` table, filled by `enrich_routes`) rather than computed per request.
- A route that can't answer an active filter is left out and counted in `unknown`, not treated as zero.

**Measurements:** after this run's background `build_route_profiles` finished, `enrich_routes` was re-run.
- **Adirondacks:** 269 of 270 routes now have gain and difficulty. One route failed in 3DEP: the service kept returning 502s.
- **White Mountains:** 182 of 182.
- When the PR merged, only 24 routes had a profile, so the gain and difficulty filters now cover almost every route.

**Protected files:** none.

### 3. TM05-79: export a trail as GPX (PR #67, merged)

**AC:**
- [x] A GPX 1.1 endpoint, with the route as a track and `<ele>` from the stored profile.
- [x] Campsites within the selected distance are named waypoints.
- [x] A **Download GPX** button.
- [x] **XSD validation in tests.** The schema is vendored unchanged at `tests/fixtures/gpx-1.1.xsd`, sha256 `9e4d1988…f34d6`.
- [x] Lat/lon order checked against known points.
- [x] Documented in docs/api.md.

**Endpoints:** `/api/routes/<osm_id>/gpx/`, plus `/api/trails/<way>/gpx/` for assembled trails.

**Dependency:** `xmlschema==4.1.0`, **test-only**. The standard library can't validate XSD. It is pure Python (no libxml2 build, unlike lxml), MIT-licensed, and its one dependency is `elementpath`. GPX is written with the stdlib `xml.etree`.

**Measurements:** Van Hoevenberg Trail, in 0.5 s: 69 KB, 862 track points all with elevation, and 8 waypoints. The sample is in `artifacts/tm05-79/`.

**Judgment call:** track points are the line's vertices merged with the profile's sample points. That keeps both the line's shape and the elevation detail.

**Protected files:** none.

### 4. TM05-80: custom waypoints (PR #68, merged)

**AC:**
- [x] Create, rename, edit the note on, and delete, with types water, camp, bail-out and custom.
- [x] Saved per account, and shown on the map with a distinct colour and glyph per type.
- [x] Cross-user isolation: another user's waypoint returns 404, and the owner always comes from the token, never the body.
- [x] Nearby waypoints included in the route GPX, when a token is sent.
- [x] Tests for create, edit, delete, signed-out access (401), isolation, and account deletion cascading.
- [x] docs/api.md.

**Where it lives:** the model is in a **new `backend/planning/` app**, with a CASCADE foreign key to `User`.

**Judgment calls:**
- **HTML markers** rather than a symbol layer, because a person has tens of waypoints. This avoids a sprite sheet and any edit to `layers.ts`.
- A cap of 1,000 waypoints per user.
- Waypoints use the same "within" distance as campsites for the GPX.
- Signed-in GPX downloads are fetched with the token header and saved as a blob. A plain link can't send the token.

**Protected-file edits:**
- `backend/config/settings.py` (Bleron): +1 line, `"planning"` in `INSTALLED_APPS`. The GDAL handling is untouched.
- `pyproject.toml` (TM05-50): `"planning"` added to ruff's `known-first-party`. The coverage floor and CI rules are untouched.
- `backend/config/urls.py`: +1 line, `include("planning.urls")`.
- `backend/accounts/`: **untouched**. Its existing all-FKs-cascade test passes with the new models.

### 5. TM05-81: plan overnight stops (PR #69, merged)

**AC:**
- [x] Choose stops from the trail panel: **+ Night** on each campsite row, which becomes "Night N" once ordered.
- [x] Each day's distance, gain and loss come from the **stored** route profile between stop positions. A test proves no 3DEP call is made once the profile is stored.
- [x] Plans are saved per account, and can be reopened or deleted from "Your plans for this trail".
- [x] Stops are ordered along the route. Off-end stops are rejected with a clear message, for example: "Wilderness Campground at Heart Lake is off the end of Van Hoevenberg Trail: it lies before the trail's start, 151 m from the trail. Choose a campsite along the trail."
- [x] The plan GPX includes the stops ("Night N: …") and the user's nearby waypoints.
- [x] Tests for the day maths, ordering, and isolation.

**Brief extras:**
- Each stop's legality verdict is shown, and any stop that isn't "Permitted" gets a warning above the day table.
- The models are in the planning app.

**Measurements:**
- **Van Hoevenberg Trail, 2 nights** (Phelps Brook Lean-to, then Marcy Dam #2 Lean-to):
  - Day 1: 1.8 mi, +206 ft / −101 ft
  - Day 2: 0.5 mi, +91 ft / −25 ft
  - Day 3: 4.7 mi, +3,010 ft / −37 ft
  - Total gain 3,306 ft against the panel's route gain of 3,305 ft. Both stops are designated, so there were no warnings.
- **A plan with an undesignated site:** "Night 2, Campsite near Van Hoevenberg Trail: Unknown: check current rules. …".

**Judgment calls:**
- **Day gain and loss.** The whole profile is smoothed once with the route's 100 m window, then each day is counted with the route's 3 m threshold.
  - A one-day plan therefore equals the route's own gain and loss exactly.
  - Across several days, the threshold restarts at each stop, so the days' sums can differ by up to about 3 m per stop. On the synthetic test profile: 190 m against 194 m.
- **Direction.** Plans run in the route's own direction, start to end. There is no reverse option yet.
- **Reopening.** Plans are reopened from the trail's own panel. There is no app-wide "My plans" list yet; that is a possible follow-up.
- **Stop distance.** A stop must be within 5 km of the trail, the panel's largest "within" option.

**Protected files:** none beyond the planning app (mine) and my trail panel files.

### 6. TM05-83: contour lines (PR #70, merged)

**AC:**
- [x] Generated from the existing Terrarium DEM, using the same exported `TERRAIN_TILES` URL. No new tile source.
- [x] In feet, with a heavier, labelled index line every fifth line.
- [x] Visible from zoom 12, with a Contours toggle in the layer panel.
- [x] Readable on Map and Satellite, with a separate set of `--map-contour-*-imagery` tokens.
- [x] Dependency justified in the PR.

**Dependency:** `maplibre-contour@0.1.1`. It is BSD-3-Clause, has **no dependencies**, adds **about 10 KB gzipped**, and contours in a **web worker**. The alternatives were server-side tiles (which the AC excludes) or our own marching squares plus a vector tile encoder.

**Measurements (Marcy Dam):**
- z11: no contours.
- z13: 392 lines, 78 of them index lines (20%), at a 40 ft interval.
- z15: a 20 ft interval.
- Labels only on index lines.

**Judgment calls:**
- 40 ft contours with a 200 ft index at z12–13, and 20 ft with a 100 ft index from z14. These are USGS topo conventions.
- Contours are on by default, because they are drawn only from z12.

**Shared-file edits:**
- `frontend/src/map/layers.ts`: one word, `export` on `TERRAIN_TILES`, in my terrain section. **Sahaj's marker paint is untouched.**
- `LayerPanel.tsx`: a Contours row.
- `satellite.ts` (mine): the imagery goes beneath the contours.

### 7. TM05-78: open the map at the user's location (PR #71, merged)

**AC:**
- [x] Asks on the map page and centres there when granted (zoom 12, with a blue location dot).
- [x] Falls back to the default region when denied or unavailable. **A denial is remembered** in `localStorage`, so the user isn't asked on every load; MapLibre's locate button asks again.
- [x] Outside every covered region: a clear notice naming the nearest region with "about N km" and a **Go to …** link.
- [x] Works on localhost. **docs/deployment.md** says geolocation needs HTTPS.

**Tests with mocked geolocation:**
- inside coverage (Lake Placid)
- outside coverage (Burlington VT, Portland ME, Denver)
- denied: remembered, and not asked again
- unavailable or timeout
- no geolocation
- storage that throws

**Browser check:** reproduced all three cases with DevTools geolocation overrides. Portland ME: "White Mountains … about 60 km away", and the link flew there.

**Judgment calls:**
- **Outside coverage**, the map still centres on the user, so it never implies there is data there, and the notice says so plainly.
- If the user has already started panning, the map isn't moved.
- The position never leaves the browser.

**Protected-file edits:** `docs/deployment.md` (Bleron): one bullet under HTTPS, as the story requires.

### 8. TM05-84: slope-angle shading (PR #72, merged)

**AC:**
- [x] Documented bands: 27–30, 30–35, 35–45 and 45+ degrees, computed from the existing DEM.
- [x] A legend with the note "Terrain information, not an avalanche forecast."
- [x] A layer-panel toggle with an opacity slider.
- [x] Band values for known test tiles verified in tests.

**Method:**
1. A custom MapLibre protocol (`campsite-slope://`) hands each tile to a **web worker**.
2. The worker decodes the Terrarium tile without colour management and smooths it (two 3×3 mean passes).
3. It computes **Horn's-method** slope with per-row Mercator pixel size, then bands it.

The colours are `--slope-*` tokens. There is no new dependency.

**Tests:** synthetic Terrarium planes of 10°, 28.5°, 32.5°, 40° and 52° at the Adirondacks' z14 tile row each land entirely in their band. The tests also cover exact plane recovery including edges, any aspect, a cliff tile, terrace removal, and the latitude scaling (6.87 m/px).

**Effective DEM resolution and limits** (documented in docs/terrain.md):
- About 6.9 m per pixel at z14 and 44°N, from roughly 10 m 3DEP data.
- After smoothing, each slope is averaged over about 35 m, so features narrower than about 30 m read less steep.
- Like-for-like share of one High Peaks tile found to be ≥30°: 9.8% from a z12 DEM, 13.4% from z13, 15.4% from z14, 16.2% from z15.
- **So the layer starts at zoom 13.**

**Judgment calls:**
- **Smoothing:** without it, Terrarium's quantisation terraces drew false 27–30° streaks.
- **Zoom 13 start:** see the limits above.
- **Tiles computed up to z14** and stretched beyond.
- **Off by default.**

**Shared-file edits:** `LayerPanel.tsx`, a Slope angle row with its legend.

---

## All protected or teammate-file edits this run

All of these are minimal and made only to keep things working:

| File | Owner | Edit | Story |
|---|---|---|---|
| `backend/config/settings.py` | Bleron | +`"planning"` in `INSTALLED_APPS` | TM05-80 |
| `pyproject.toml` | Bleron (TM05-50) | +`"planning"` in ruff `known-first-party` | TM05-80 |
| `backend/config/urls.py` | shared | +`include("planning.urls")` | TM05-80 |
| `docs/deployment.md` | Bleron | +1 bullet: geolocation needs HTTPS | TM05-78 |
| `frontend/src/map/layers.ts` | shared (Sahaj's marker paint) | `export` on `TERRAIN_TILES`, in my terrain section | TM05-83 |
| `frontend/src/components/LayerPanel.tsx` | shared | Contours and Slope angle rows | TM05-83, TM05-84 |

**Not touched:**
- `backend/accounts/`
- the Saved panel's names (TM05-87)
- the marker paint in `layers.ts`
- score colouring on map markers (TM05-86 and TM05-72). It was not implemented.

**Dev-environment notes:**
- Ran the `planning` migrations (0001 and 0002) against the dev database.
- Created three throwaway accounts (`wpdemo…`, `plandemo…`) for the browser checks, then deleted them with their waypoints, plan and tokens.
- Stopped the backend, Vite and headless Chrome I started. Nothing else was stopped.

## Observations to check by eye

- **Elevation chart width.** In one headless screenshot of the trail panel (TM05-79), the elevation chart drew narrower than the panel. It looked like a measure-before-layout race in headless Chrome, and I didn't change anything for it. Confirm in a real browser that the chart fills the panel width.
- **One Adirondack route** still has no profile, because 3DEP returned 502s. `build_route_profiles adirondacks` will retry it.

---

## Browser checklist: the full demo flow

Use a real browser on `http://localhost:5173`, with `make dev` or the backend on 8000 and Vite on 5173.

1. **Open on location.**
   - Go to `/discover`. The browser asks for your location.
   - **Allow:** in the Adirondacks or White Mountains, the map centres on you at zoom 12 with a blue dot. Anywhere else, a notice at the bottom names the nearest region with "about N km" and a **Go to the …** link. Click it and the map flies there.
   - Clear site data and **Block** instead: the map stays on the Adirondacks.
   - Reload: you are **not** asked again.
   - The locate button (bottom right, above zoom) asks again.
2. **Search a trail.** In the search box at the top centre, type `van hoev`. Both Van Hoevenberg trails appear.
3. **Filter.**
   - Clear the search box. "Trails near this view" lists nearby trails, nearest first.
   - Open **Filters** and choose **Loop**, then **Hard**. The list narrows, and almost every route now has gain and difficulty.
   - **Clear filters** restores the list.
4. **Open it.** Pick **Van Hoevenberg Trail**. The trail panel opens, and the map fits the trail. Check:
   - the stats: distance, gain, loss, high point, max grade, difficulty, type, time
   - the elevation chart, which should be the full panel width
5. **View contours and slope shading.**
   - Zoom to 13 or more near Marcy Dam and Avalanche Lake. **Contours** show in feet, with labelled index lines.
   - In the layer panel, turn on **Slope angle**. Check:
     - the legend (27–30, 30–35, 35–45, 45+)
     - the note "Terrain information, not an avalanche forecast."
     - the opacity slider, which changes the shading
   - The Colden slides and the Avalanche Lake cliffs show red and purple.
   - Switch to **Satellite**: contours turn pale and both overlays stay above the imagery. Switch back to **Map**.
   - Zoom to 11: no contours. The panel shows "zoom 12+" for contours and "zoom 13+" for slope.
6. **View the campsites along it and their verdicts.**
   - In the panel's campsite list, click **Phelps Brook Lean-to**. The campsite panel shows **"Permitted · designated site"** above the score, with the reason and the DEC rule.
   - Open a "Campsite near Van Hoevenberg Trail". It reads **Unknown: check current rules**.
   - Close the campsite panel to return to the trail.
7. **Plan two nights** (sign in or create an account first).
   - In the campsite list, click **+ Night** on Marcy Dam #2 Lean-to, then on Phelps Brook Lean-to. The buttons become **Night 2** and **Night 1**: the stops are ordered along the trail, not by click order.
   - The Overnight plan table shows 3 days, each with distance, gain, loss and the stop's verdict. Add an undesignated site to see the warning, then remove it.
   - The "+ Night" on Wilderness Campground at Heart Lake is disabled, because it is past the trail's start.
   - Name the plan and click **Save plan**. It appears under "Your plans for this trail".
   - Click **New plan**, then **Open** on the saved plan: the stops come back.
8. **Add a waypoint.** Under **My waypoints**, click **+ Add**, then click the map near the trail.
   - Choose **Water**, add a note, and **Save**. A blue drop marker appears.
   - Click it to rename it, then **Save**.
9. **Export GPX.**
   - In the trail panel, **Download GPX** saves `van-hoevenberg-trail.gpx`: the track with elevations, every campsite within 500 m, and your waypoint.
   - In the plan section, **Download plan GPX** saves the plan: the track, "Night 1: Phelps Brook Lean-to", "Night 2: Marcy Dam #2 Lean-to", and your nearby waypoint.
   - Open either file in a GPX viewer (for example gpx.studio) to check the track sits on the trail.
10. **Clean up (optional).** Delete the waypoint (Delete, then Really delete?) and the plan.
