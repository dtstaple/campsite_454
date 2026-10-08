# Run report: Sprint 5, final stories (2026-10-08)

This was an unattended run. It created six new Sprint 5 stories and implemented them in
the order A, B, C, E, D, F.

**Every story is merged** to `main` with a merge commit after green CI. Each branch was cut
from an up-to-date `main`, and every commit leads with its key.

**Rules kept:**
- no force-push, no direct push to `main`, no secrets committed
- no `docker volume prune` or `docker system prune`
- no worklogs, and nothing moved to Done

**Jira.** All six stories were created in **Sprint 5** (id 72), assigned to **Davis
Stapleton**, each with a description and AC in `customfield_10044`.
- **Points field.** It was read from TM05-42 first, and is `customfield_10016` ("Story
  point estimate").
- **Points read back:** 2, 8, 5, 3, 5 and 5.
- **Status.** Each story was moved to **In Progress** when it was started, and is still In
  Progress. Each has a comment with its PR link and a summary.

**`make doctor`:** all checks pass. The one warning is the existing `.env` SECRET_KEY
dev fallback.

**Final gate on `main`:**
- backend: `ruff check`, `ruff format --check`, and `pytest` with **823 passed**, and
  coverage above the 93% floor
- frontend: `npm run lint` (1 warning, the long-standing one in `session.tsx`),
  `npm run build`, and `npm test` with **109 passed**

| Brief | Story | PR | Status |
|---|---|---|---|
| A | TM05-98 Stitch named trails across short unnamed connectors (2) | [#74](https://github.com/dtstaple/campsite_454/pull/74) | merged |
| B | TM05-99 Find potential campsites along a trail (8) | [#75](https://github.com/dtstaple/campsite_454/pull/75) | merged |
| C | TM05-100 Profile page with saved trails, campsites, waypoints and plans (5) | [#76](https://github.com/dtstaple/campsite_454/pull/76) | merged |
| E | TM05-101 Show connecting trails at junctions (3) | [#77](https://github.com/dtstaple/campsite_454/pull/77) | merged |
| D | TM05-102 Discover page: browse trails like AllTrails (5) | [#78](https://github.com/dtstaple/campsite_454/pull/78) | merged |
| F | TM05-103 Phone-ready layout with live GPS location (5) | [#79](https://github.com/dtstaple/campsite_454/pull/79) | merged |

**Rollover comment drafts: none.** Every story finished and merged.

**CI fix attempts:** two stories needed one each, both test problems rather than code bugs.
- **TM05-99.** A station count assumed exactly 4,000 m, but the line round-trips through
  EPSG:4326, so its length is a hair either side. The test now counts stations on the
  same stitched line.
- **TM05-103.** pytest-cov followed a settings subprocess and produced statement data
  that couldn't combine with the suite's branch data. The subprocess now runs without
  the coverage variables.

---

## A. TM05-98: stitch named trails across short unnamed connectors (#74, merged)

**AC:**
- [x] Assembly bridges gaps through **unnamed** ways whose combined length is at most
  `assembly.connector_max_m` (**300 m**, in `backend/geodata/routes.yml`). Each must share
  `osm_node_ids` with both same-name pieces.
- [x] **Never through another named trail.** The search only steps onto unnamed ways.
- [x] Measured, including Cheney Pond-Irishtown.
- [x] **Tests:** a bridged gap, a two-connector chain, a connector too long, connectors
  adding up past the limit, a named connector, a stub to nowhere, symmetry, and the off
  switch.

**Measurements** (5,855 named non-route ways):
- **Assembled trails:** 4,043 → **4,017**.
- **25 trails** now use 34 connectors, merging 26 pieces. **16 of those 25 now draw as one
  continuous line**, for example S86A, Rim Walk Trail and Snowmobile Route S82.
- **Names split** into more than one trail: 296 → 286.
- **Cost:** 119 s against 117 s for all 4,000 assemblies, about 0.5 ms per click.
- **Cheney Pond-Irishtown** (`way/1089777523`) is **already one continuous 12.8 km way**
  in our data. Its only touching way is an **unnamed 3.5 km track**, which is correctly
  *not* bridged, being far over the limit.

**Judgment calls:**
- **Shortest path.** It takes the shortest connector path (Dijkstra, ties by way id), so
  the trail and its cached profile are the same from either side.
- **Chains.** Chains of unnamed connectors count against the limit as one total.

**Protected-file edits:** none.

## B. TM05-99: find potential campsites along a trail (#75, merged)

**AC:**
- [x] Mapped campsites are **off by default in both modes**, and still toggleable.
- [x] The panel shows a prompt ("Planning an overnight? Find places to camp along this
  trail.") and a prominent **Find campsites along this trail** button. It shows the mapped
  campsites **and** runs the candidate search.
- [x] Results are on the map and in one list ordered by mile, even with the Campsites
  layer off.
- [x] **+ Night** on every result. Nights show as numbered markers on the map.
- [x] **A new endpoint:**
  - `GET /api/routes/<id>/candidates/` and `/api/trails/<way>/candidates/`
  - cached per route geometry, corridor and config, in the analysis cache (30 days)
  - samples every 200 m, offset 60–1,000 m each side, inside the user's "within"
- [x] **Hard filters** (metre-correct, indexed `ST_DWithin` on `geom_m`; the existing 3DEP
  sampler):
  1. open-access public land
  2. ≥ 150 ft from any trail
  3. ≥ 150 ft from water
  4. the DEC elevation rules from TM05-76, with their 50 ft margin
  5. slope ≤ 5° (in config)
- [x] Scored with the existing engine, spread ≥ 805 m (about 0.5 mi) apart, and capped at 8.
- [x] **Honest labelling:**
  - every candidate is labelled **"Potential spot (unverified)"**
  - a **dashed-ring** marker from new `--candidate-*` tokens, never the score colours
  - a new **`computed`** confidence level in the TM05-77 rules
- [x] The detail popup **lists each check passed**, with measured values, and says
  **"Road distance isn't checked; verify current rules on the ground."**
- [x] An empty result **says why**, for example "No public land with gentle slope (≤ 5°)
  within 1 km of this trail."
- [x] A candidate added as a night carries the **unverified-stop plan warning**. In the
  plan GPX it is `overnight-stop:unverified`.
- [x] Runtime and per-filter rejections measured (below).
- [x] **Tests:** each hard filter, the spread rule, an empty result, labelling on every
  candidate, caching, and candidates as nights.

**Measurements** (corridor 500 m; "cold" means no search or slope stencil cached):

| Trail | Sampled | public_land | trail | water | elevation | terrain | slope | Passed | Kept | Cold | Cached |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Cheney Pond-Irishtown | 650 | 60 | 5 | 75 | 0 | 0 | 420 | 90 | 8 | **32.3 s** | 4 ms |
| Deer Pond Trail | 290 | 22 | 5 | 42 | 0 | 0 | 130 | 91 | 5 | **15.3 s** | 3 ms |
| Van Hoevenberg Trail | 570 | 44 | 71 | 44 | 207 | 0 | 173 | 31 | 3 | **19.2 s** | 3 ms |

Cold time is almost all 3DEP. Checking elevation (1 sample per point) before the slope
stencil (9 per point) took Van Hoevenberg from 33.5 s to 19.2 s cold. The panel tells the
hiker the first search can take up to half a minute.

**Judgment calls:**
- **Distance from trails.** "150 ft from the trail" is measured from **any** mapped trail,
  as the DEC rule says.
- **Elevation margin.** Points within the verdict's 50 ft margin of a limit are rejected.
- **What gets scored.** Only the flattest survivor per station, at most 60, because
  scoring costs about 0.1 s a point.
- **Weather** is left out of candidate scores, because the answer is cached for weeks.
- **Plan stops.** A candidate is stored as a plan stop by its position
  (`candidate/<lon>,<lat>`).
- **Cache cleanup.** I deleted the 412 slope-stencil and 3 candidate cache rows created by
  my own trial runs, to take honest cold measurements and to drop wording I then changed.

**Protected areas:**
- score colours on mapped markers (TM05-72, TM05-86): untouched
- `backend/accounts/`: untouched
- the saved-campsites endpoint: untouched

## C. TM05-100: Profile page (#76, merged)

**AC:**
- [x] **The floating Saved panel is replaced** by a Profile view (`/profile`, linked from
  the header when signed in). It has tabs for Saved campsites, Saved trails, Waypoints and
  Overnight plans. `SavedPanel.tsx`, my own file, and its CSS are deleted.
- [x] **Save trail** in the trail panel, backed by a new `SavedTrail` model in the
  planning app (`/api/saved-trails/`).
- [x] **Clicking any item** flies there and opens its panel, even with the layer off:
  - a campsite opens with the **TM05-69 raised pin**
  - a trail opens the trail panel
  - a waypoint opens its editor
  - a plan loads into its trail
- [x] **Campsite names** come from the **detail endpoint's display name**, including
  derived ones. The list endpoint is unchanged (TM05-87).
- [x] Every tab has a clear empty state.
- [x] **Tests:** saved-trail CRUD and isolation; frontend mapping of each item to the right
  panel; browser checks of each.

**Browser check:**
- the empty states
- a derived name ("Campsite near Van Hoevenberg Trail")
- each item opened its panel
- a reload did not reopen anything

**Judgment calls:**
- **How items open.** Profile items open through router state, taken once, and the
  history entry is then replaced.
- **Plans with candidate nights.** Opening a plan also opens the campsite finder, because
  its nights may be potential spots.

**Protected areas:** `backend/accounts/` and the saved-campsites endpoint are untouched.

## E. TM05-101: connecting trails at junctions (#77, merged)

**AC:**
- [x] **Connects to** lists named trails that share a junction node (`osm_node_ids`), with
  each junction's mile.
- [x] Clicking one opens it.
- [x] Hovering one rings its junctions on the map (`--junction-*` tokens).
- [x] **Tests:** a shared node is a junction at the exact mile; a crossing without a
  shared node is not; unnamed and same-name ways are excluded; mile order; double
  junctions; route identity.

**Not built: multi-trail route planning.** Combining connected trails into one planned
hike is a **future story**, as the brief asked. It is noted in docs/routes.md.

**Measurements:**
- Van Hoevenberg has **13** connecting trails, from mi 0.1 to mi 7.1.
- 87–149 ms per request, after batching the route lookup (463 ms before).
- Algonquin links back to Van Hoevenberg.

**Also fixed here:** the trail panel is a scrolling flex column. It was squeezing the
elevation chart's SVG, which made it narrow, and then zero-height once the panel grew. This
was the "narrow chart" seen in the previous run's report. Panel sections no longer shrink.

**Protected-file edits:** none.

## D. TM05-102: Discover page (#78, merged)

**AC:**
- [x] A full **Discover trails** page (`/trails`) with:
  - a **region selector** from `regions.yml` (new `GET /api/regions/`, with trail counts;
    empty regions disabled)
  - the TM05-85 filters
  - a **sort**: distance from the map view, longest, most climbing, or name
- [x] **Cards** show name, distance, gain, difficulty, route type, a **sparkline from the
  stored profile**, and the **campsites within 500 m**.
- [x] Clicking a card opens the map with that trail's panel, and fits the view to it.
- [x] It **reuses the TM05-74/85 endpoint**, which gains `region`, `sort`, `offset` and
  `cards`. Results come **24 per page** with Show more.
- [x] **Tests:** region filtering, sorting, pagination, card data, and the regions
  endpoint.

**Measurements:**
- About 0.4 s per 24-card page.
- Adirondacks: 270 trails. White Mountains: 182.
- The Hard filter left 23, with the "no elevation data" note for 1.

**Judgment calls:**
- **Region boundary.** A route belongs to every region its bounding box overlaps, so
  long-distance trails appear in each. Green Mountains shows 1 trail from that overlap.
- **Header.** It now reads **Discover trails** (`/trails`) and **Map** (`/discover`).
- **Distance sort.** It uses the map's last centre when that is inside the region,
  otherwise the region centre.
- **Exact-shape test.** `test_route_search.py`'s exact-response test now includes the
  additive fields.

**Protected-file edits:** none.

## F. TM05-103: phone-ready layout with live GPS (#79, merged)

**AC:**
- [x] **Below 640 px the side panels are draggable bottom sheets** (peek 132 px, half,
  full): drag, flick or tap. The `viewport-fit=cover` meta and `env(safe-area-inset-*)`
  keep controls clear of the notch and home bar.
- [x] The **elevation scrubber and the map work by touch**, checked with emulated touch.
- [x] **Live location:**
  - a GPS dot and a metre-correct accuracy circle
  - **Follow me**, which keeps the map centred and stops when the map is dragged
  - **"mi X.X along <trail>"** while within 150 m of the open trail
- [x] A **web app manifest** and icons for Add to Home Screen. **No offline support.**
- [x] **Phone testing:** `make dev-phone`.
  - Vite's basic-SSL plugin serves HTTPS on the LAN and proxies `/api`.
  - **`DEV_LAN_ORIGIN` is trusted for CORS and CSRF in dev settings only, while DEBUG is
    on.** A test checks it is ignored with DEBUG off.
  - **docs/setup.md** explains how to open it from an iPhone.
- [x] **Checked headless at 390 × 844:**
  - sheet half 405 px, then full 753 px (tap), then peek 132 px (drag)
  - touch scrub
  - GPS dot, "±18 m" and "mi 2.1", then Follow me re-centred to "mi 2.5"
  - no horizontal scroll, and the manifest is served
  - desktop rechecked at 1440

**Smoke test of phone mode.** Served on a spare port (5174): the page was **HTTPS**,
`/api/regions/` came back through the proxy, and Vite reported the LAN address.

**New dependency:** `@vitejs/plugin-basic-ssl@2.3.0`, **dev only**. It is MIT, from the
Vite team, and used only with `PHONE=1`.

**Judgment calls:**
- **One location control.** Live location replaces TM05-78's MapLibre locate button. The
  start dot gives way to the live one.
- **Zoom buttons.** They are hidden while a sheet is open, since pinch replaces them.
- **Folded on a phone.** The trail list and the layer panel start folded.
- **Icons.** Drawn as an SVG (a tent under a ridge, in theme colours) and rasterised with
  headless Chrome. They replace Vite's default favicon.

**Not checkable headless:** real safe-area insets (Chrome reports 0), outdoor GPS, and iOS
Add to Home Screen. These are covered by the phone checklist below.

---

## Protected or teammate-file edits this run

All of these are minimal:

| File | Owner | Edit | Story |
|---|---|---|---|
| `backend/config/settings.py` | shared (Abdulrahman, Bleron, Davis) | +8 lines: dev-only `DEV_LAN_ORIGIN` after `CORS_ALLOWED_ORIGINS`; GDAL handling untouched | TM05-103 |
| `.env.example` | shared | a commented `DEV_LAN_ORIGIN` entry, since every variable settings reads is listed | TM05-103 |
| `docs/setup.md` | shared (Bleron) | a new "Testing on a phone" subsection | TM05-103 |
| `frontend/vite.config.ts`, `frontend/index.html` | shared (Sahaj) | phone mode; manifest and viewport meta | TM05-103 |
| `frontend/src/components/LayerPanel.tsx` | shared | folded by default on a phone | TM05-103 |
| `tests/test_route_search.py` | mine | the exact-shape assertion includes the additive fields | TM05-102 |

**Not touched:**
- score colours on mapped markers (TM05-72, TM05-86)
- `backend/accounts/`
- the saved-campsites list endpoint (TM05-87)

**New saved-trail models** are in the planning app, as asked.

**Dev-environment notes:**
- Applied `planning` migrations 0003 (candidate stops) and 0004 (saved trails) to the dev
  database.
- Created throwaway accounts for the browser checks (`finddemo…`, `profempty…`,
  `profdemo…`) and deleted all 7, with their tokens, saved items, waypoints and plans.
- Stopped only the backend, the Vites and the headless Chrome I started.

---

## Phone-testing checklist (a real iPhone, over HTTPS)

1. **Start it.** On the laptop, run `make dev-phone`. Note the printed address, for
   example `https://192.168.1.20:5173/discover`. The phone must be on the same Wi-Fi.
2. **Open it** in **Safari** on the iPhone. The certificate warning is expected: tap
   **Show Details → visit this website**, then confirm.
3. **The notch and home bar:** the header text sits below the notch and status bar, and
   nothing is hidden behind the home bar at the bottom.
4. **Location:**
   - When asked, **Allow** location.
   - Tap **Location** (bottom left). A blue **GPS dot** appears with a translucent
     **accuracy circle**, and the button reads "±N m".
   - Walk a few steps: the dot moves.
5. **Follow me:**
   - Tap **Follow me**. The map centres on you, and keeps centring as you move.
   - Drag the map: Follow me switches off.
6. **On a trail.** Search a nearby trail and open it. While you're within 150 m of it, the
   panel shows **"mi X.X along <trail>"**, and it updates as you walk.
7. **Bottom sheets:**
   - The trail panel opens as a **half** sheet.
   - **Drag** the grip up to **full**, and down to **peek**.
   - **Tap** the grip to cycle.
   - Location, Follow me and Map/Satellite stay just above the sheet.
8. **Touch:** drag a finger across the **elevation chart**. The readout and the trail
   marker follow. Pinch-zoom and pan the map.
9. **Home screen:**
   - **Share → Add to Home Screen.** The CampSite icon (a tent under a ridge) appears.
   - Opening it is full-screen, with no Safari bars.
   - Offline, it shows nothing new: there is no offline support, by design.

## Desktop demo checklist

Use a real browser on `http://localhost:5173`, with `make dev`, signed in.

1. **Discover.** Open **Discover trails** in the header.
   - Choose **Adirondack Park**, sort by **Most climbing**, and open **Filters → Hard**.
   - The cards show distance, gain, difficulty, type, a sparkline and a campsite count.
   - Clear filters, then **Show more**.
2. **Pick a trail.** Click the **Van Hoevenberg Trail** card. The map opens with its panel,
   fitted to the trail. The elevation chart fills the panel width.
3. **Connecting trails:**
   - In **Connects to**, hover **Marcy Dam Truck Trail**: two junction rings appear on
     the trail.
   - Click **Algonquin Trail**: it opens, and lists Van Hoevenberg back. Return to Van
     Hoevenberg by clicking it.
4. **Find campsites:**
   - Before clicking, the panel shows "Planning an overnight? Find places to camp along
     this trail."
   - Mapped campsites are **off** in the layer panel.
   - Click **Find campsites along this trail**. The first search of a trail can take up to
     about 30 s; it is instant after that.
   - The list mixes mapped campsites and **Potential spot (unverified)** rows, by mile.
   - On the map, mapped sites are solid red and potential spots are **dashed rings**.
   - Click a potential spot. Its popup lists the checks it passed and says "Road distance
     isn't checked; verify current rules on the ground."
5. **Add two nights:**
   - From the popup, add the potential spot with **+ Night**.
   - Add **Phelps Brook Lean-to** with **+ Night** in the list.
   - The map shows numbered markers **1** (dashed edge, unverified) and **2**.
   - The plan shows the unverified-stop warning and three days of distance, gain and
     loss.
   - Name the plan and click **Save plan**.
6. **Save the trail:** click **Save trail**. It changes to "Saved".
7. **The Profile view.** Open **Profile** in the header. Then:
   - **Saved trails**: Van Hoevenberg Trail. Click it: the map opens its panel.
   - **Overnight plans**: click the plan. The trail opens with Night 1 and Night 2 in
     place.
   - **Saved campsites** and **Waypoints**: their empty states, or your items, which open
     their panels on the map (a campsite with its raised pin).
8. **GPX export.** In the trail panel:
   - **Download GPX** saves the track, campsites and your waypoints.
   - In the plan section, **Download plan GPX** saves the track, "Night 1: Potential spot
     (unverified)" (type `overnight-stop:unverified`) and "Night 2: Phelps Brook Lean-to".
