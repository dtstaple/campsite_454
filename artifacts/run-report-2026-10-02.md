# Run report — 2026-10-02

Autonomous run over Davis Stapleton's Sprint 4 stories (Phase 1) and the trail-insight
extension (Phase 2). Nothing was merged, nothing was pushed to `main`, nothing was moved to
Done, and no worklogs were created.

Pre-flight checks: `gh auth status` showed logged in as `dtstaple` (git protocol ssh,
token scopes include `repo`). The Atlassian MCP read TM05-42, including its Acceptance
Criteria in `customfield_10044`. TM05-56 (backcountry UI shell) was already merged as PR
#29, so the stack starts from `main` at `b851dde`.

Field ids found by reading TM05-43 with all fields: story points `customfield_10016`,
sprint `customfield_10020` (Sprint 4 = id 71), Acceptance Criteria `customfield_10044`.

---

## 1. Stories and PRs

| Story | What | Branch | PR | Base | Jira |
|---|---|---|---|---|---|
| TM05-42 | Metre-correct, indexed distance queries | `TM05-42-metre-distance-queries` | [#30](https://github.com/dtstaple/campsite_454/pull/30) | `main` | In Progress, PR comment |
| TM05-43 | Scoring engine + output contract | `TM05-43-scoring-engine` | [#32](https://github.com/dtstaple/campsite_454/pull/32) | #30 | In Progress, PR comment |
| TM05-44 | Analysis/cache layer, weather first | `TM05-44-analysis-cache-weather` | [#33](https://github.com/dtstaple/campsite_454/pull/33) | #32 | In Progress, PR comment |
| TM05-41 | Coding standard | — | (existing #31, not mine) | — | skipped, see §2.4 |
| TM05-57 *(new)* | Repair invalid PAD-US geometry | — | — | — | backlog, 3 pts |
| TM05-58 *(new)* | Named hiking routes from OSM relations | `TM05-58-hiking-routes` | [#34](https://github.com/dtstaple/campsite_454/pull/34) | #33 | Sprint 4, 5 pts, In Progress, PR comment |
| TM05-59 *(new)* | Route elevation profiles from 3DEP | `TM05-59-route-elevation-profiles` | [#35](https://github.com/dtstaple/campsite_454/pull/35) | #34 | Sprint 4, 5 pts, In Progress, PR comment |
| TM05-60 *(new)* | Route API: listing + detail | `TM05-60-route-api` | [#36](https://github.com/dtstaple/campsite_454/pull/36) | #35 | Sprint 4, 5 pts, In Progress, PR comment |
| TM05-61 *(new)* | Trail panel + SVG elevation chart | `TM05-61-trail-panel` | [#37](https://github.com/dtstaple/campsite_454/pull/37) | #36 | Sprint 4, 5 pts, In Progress, PR comment |
| TM05-62 *(new)* | 3D terrain, scrubber camera, flythrough | `TM05-62-trail-3d-flythrough` | [#38](https://github.com/dtstaple/campsite_454/pull/38) | #37 | Sprint 4, 5 pts, In Progress, PR comment |
| — | This report | `TM05-42-run-report-2026-10-02` | (this PR) | `main` | — |

Every new story was created with assignee Davis Stapleton, a description, AC in
`customfield_10044` and Fibonacci points. TM05-58 to TM05-62 were added to Sprint 4 when
work started; TM05-57 stays in the backlog.

## Required merge order

The PRs are a linear stack; each is based on the one before, so its diff shows only its own
commits. Merge in this order. After each merge GitHub retargets the next PR to `main`.

```
#30 TM05-42  →  #32 TM05-43  →  #33 TM05-44  →  #34 TM05-58  →  #35 TM05-59
             →  #36 TM05-60  →  #37 TM05-61  →  #38 TM05-62
```

This report's PR is independent of the stack and can merge at any time. #31 (TM05-41)
predates this run and is independent too.

The gate (`ruff check . && ruff format --check . && pytest`, then
`npm run lint && npm run build`) passed before every commit. The final count is 556 passed,
10 deselected. Lint has 0 errors; the 3 remaining warnings were on `main` before this run.
Nothing had to be reverted.

---

## 2. Phase 1 — Sprint 4 stories

### 2.1 TM05-42 — Make distance queries correct and fast → #30

**What.** Campsites, trails and water each gain `geom_m`: `geom` projected to **EPSG:5070**
(CONUS Albers, metres). It is a PostGIS generated column
(`GENERATED ALWAYS AS (ST_Transform(geom, 5070)) STORED`) with its own GiST index.
`backend/geodata/distance.py` is the one place distance SQL is written: `nearest()`,
`nearest_k()`, `nearest_distance_m()` and `within()`. They order with the KNN operator
`<->`, so lookups walk the index. `manage.py bench_distance` reproduces the measurements.

| AC | Met? |
|---|---|
| Distance queries return real metres and use an index | ✅ |
| Approach chosen deliberately between geography index and projected column, reasoning documented | ✅ projected column; geography index measured 28× slower (docs/architecture.md) |
| Before and after times measured and recorded | ✅ table below |
| EXPLAIN ANALYZE confirms an index scan | ✅ `Index Scan using water_geom_m_gist … Order By: (geom_m <-> …)` |
| Existing spatial queries in the API still work unchanged | ✅ `geom` untouched; map-data tests pass unmodified |
| docs/architecture.md notes the change and why | ✅ new section "Measuring distance in metres" |

### 2.2 TM05-43 — Build the scoring engine → #32

**What.**
- **Contract first.** The output contract (`docs/scoring.md` §1) was its own first commit.
- **Engine.** `backend/scoring/` provides `score_location(lon, lat)` and `score_campsite()`. Factors: water, legal, trail, plus slope and land cover placeholders.
- **Water and trail** use peak curves: 35 on the bank, 100 at 60 m, halving every 400 m beyond for water and every 800 m for trail.
- **Water prefers flow.** Perennial ×1.0, unknown ×0.8, intermittent ×0.55. The best of the 5 nearest features per flow class wins.
- **Legal** uses PAD-US public access × GAP multiplier. Where parcels overlap, the most restrictive access applies, and land marked **closed** caps the overall score at 0.
- **Config.** Weights and every curve value are in `scoring/config.yml`. Each score carries a `config_digest`.
- **Capacity is not a factor.** A test asserts that capacities 2 and 40 at the same point score identically.

| AC | Met? |
|---|---|
| Score 0–100 from coordinates, not only a known campsite id | ✅ `score_location(lon, lat)` |
| Per-factor breakdown with sub-score and underlying measurement | ✅ contract 1 |
| Water curve peaks at an ideal distance; perennial weighted above intermittent | ✅ |
| Legal uses public access and GAP status; closed land scores accordingly | ✅ closed → legal 0 and total capped at 0 |
| Trail access uses a curve | ✅ |
| Weights in configuration | ✅ `config.yml` |
| Slope and land cover structured as placeholders | ✅ real factor classes returning `not_available` |
| Scoring 100 sites timed, figure documented | ✅ 934 ms (model 1.0.0) |
| Tests: each factor, combined score, edge cases (no water, no trail, unknown legal) | ✅ 40 tests at the time; 44 after TM05-44 |
| docs/scoring.md explains the model, curves and weights | ✅ |

**Data finding.** Only **199 of 1,320** ingested campsites fall inside any PAD-US parcel —
Marcy Dam in the High Peaks Wilderness scores "probably private". The cause is ingestion,
not scoring: the PAD-US runs are `partial` and **skipped 49 parcels as invalid geometry**
("Ring Self-intersection", "Nested shells"), the large wilderness and forest units among
them. Raised as **TM05-57** (backlog, 3 pts): repair with `make_valid` in the shared
pipeline step.

### 2.3 TM05-44 — Build the analysis and cache layer → #33

**What.**
- **Contract.** `backend/analysis/base.py`: `Analysis` is the on-demand counterpart of `SourceAdapter`. A subclass declares `name`, `version`, `ttl` and `grid_degrees`, and implements `compute()`.
- **Framework.** It handles the cache key, hit/miss, expiry, provenance, and purging of expired rows. A failed `compute()` caches nothing.
- **Storage.** `AnalysisResult` is the cache, with the key's parts as queryable columns.
- **Weather.** `WeatherForecast` reads Open-Meteo, snapped to a 0.05° grid and cached for 1 h.
- **Scoring.** `WeatherFactor` is the fourth data factor (model 1.1.0, weight 0.15): 100 minus capped penalties for rain, wind over 25 km/h, and frost. If Open-Meteo is down it reports `not_available` and drops out of the total.

**Weather source, verified live before use** (endpoint and shape are in
`docs/architecture.md`, the module docstring, and `tests/fixtures/open_meteo_forecast.json`):
- `GET https://api.open-meteo.com/v1/forecast?latitude=…&longitude=…&current=…&daily=…&forecast_days=3&timezone=auto`
- Returned 200 in 0.84 s, no key.
- The response has `latitude`, `longitude`, `elevation`, `timezone` and `generationtime_ms`, plus `current{time, temperature_2m, precipitation, wind_speed_10m, wind_gusts_10m, weather_code}` and `daily{time[], temperature_2m_min[], temperature_2m_max[], precipitation_sum[], precipitation_probability_max[], wind_speed_10m_max[], wind_gusts_10m_max[]}`.
- Two points 2 km apart came back as the same grid cell, which is why requests snap to a grid.

| AC | Met? |
|---|---|
| Analysis abstraction alongside SourceAdapter with its own contract | ✅ |
| Results cached by a documented key covering source, geometry, time window, parameters | ✅ sha256 over canonical JSON of all four plus version |
| TTL appropriate to the data type, documented per source | ✅ weather 1 h; table includes route_profile (1 y) and planned 3DEP/Sentinel-2/SSURGO |
| Every result records provenance | ✅ |
| Weather is the first analysis, live, feeding scoring as a fourth factor | ✅ |
| Repeat request for the same area and window served from cache | ✅ miss 734 ms → hit 4.9 ms |
| Tests: key generation, hit and miss, expiry | ✅ 28 new tests, no network |
| docs/architecture.md documents the pattern for elevation/imagery | ✅ "On-demand analysis and the answer cache", incl. "Adding the next analysis" |

### 2.4 TM05-41 — Coding Standard → skipped

Its description is empty and its only AC line is "Create Coding Standard for project". That
names no scope, format, location or reviewer, so it is not implementable to a spec. PR #31
(`TM05-41-coding-conventions`, "Add team coding conventions") already exists under
`dtstaple` from before this run; I did not touch it. **Missing from the AC:** where the
standard lives (`docs/` vs `CONTRIBUTING.md`), what it covers (Python/TS style beyond
ruff/oxlint, naming, commit and branch rules, tests, docs), and how it is enforced (CI
gates vs review).

---

## 3. Phase 2 — Trail insight with 3D

### 3.1 TM05-58 — Named hiking routes → #34

The new `osm-routes` adapter, on the existing framework with no framework changes, writes
`TrailRoute`:
- name, `osm_id`, `ref`, `network`, `operator`
- **ordered** `member_way_ids`, which join to `Trail` as `way/<id>`
- a MultiLineString with one line per main-line member, plus the generated `geom_m`
- geodesic `length_m`

Decisions:
- One query per region, no tiling.
- Side branches (`alternative` / `excursion` / `approach` / `connection`) stay in the member list but are left out of the geometry and length.
- Super-relations aren't expanded. They are skipped as having no geometry, and their section relations are ingested in their own right.
- Whole routes are stored, including parts outside the region box.

All AC met: adapter on the framework, model fields, idempotent upsert, IngestRun
provenance, nested relations documented, coverage measured (below), 10 tests on a recorded
fixture, and `docs/pipeline.md` updated.

### 3.2 TM05-59 — Elevation profiles → #35

**3DEP verified live first:**
- `POST …/3DEPElevation/ImageServer/getSamples` with a multipoint geometry. A polyline request also worked.
- 455 points in one request, ~1 s, at 1 m LiDAR resolution (NAVD 88).
- Samples arrive out of order and are matched back by `locationId`.

**Fallback.** Because 3DEP works, the Terrarium fallback was not needed. It stays documented, not built.

**`RouteProfile`** is an analysis on the TM05-44 cache. It:
1. **Stitches** the members into one ordered line. Parallel branches that don't join are left out and counted.
2. **Samples** every 25 m, capped at 2,000 samples.
3. **Smooths** with a 100 m moving average and applies a 3 m threshold for gain and loss. The naive sum is kept for comparison.
4. **Measures max grade** over ≥100 m.

It stores distance/elevation pairs and stats, never pixels, with a one-year TTL, keyed by
route geometry. `manage.py route_profile` prints the calibration and a sensitivity table.

All AC met (verified live, stitching, stored profile with provenance, smoothed and
thresholded gain, windowed max grade, Marcy calibration, 19 tests without network).

### 3.3 TM05-60 — Route API → #36

New file `backend/api/routes.py`:
- **`GET /api/routes/?bbox=`** returns GeoJSON, longest first, with `limit` and `simplify`.
- **`GET /api/routes/<osm_id>/`** returns:
  - the route and its stitched `line`
  - the profile, or `status: "unavailable"` while the rest still returns
  - campsites within `campsites_within_m` (default 500, max 5000), ordered along the route by `ST_LineLocatePoint`, with metre distances along and from the route and each one's contract-1 score

Documented in `docs/api.md` with real examples. All AC met, with 9 tests.

### 3.4 TM05-61 — Trail panel → #37

New `frontend/src/trails/`.
- **Map.** Named routes are drawn in view. Clicking one opens the panel without the segment popup.
- **Stats.** Distance, gain, loss, high point, max grade, and Naismith time (method in the tooltip).
- **Chart.** A dependency-free SVG elevation chart, linked both ways with the map (chart hover → map marker; route hover → chart cursor).
- **Campsites along this trail.** Listed by mile marker with score, within a selectable distance.
- **States.** Loading, error, profile-unavailable and none-found states.

All AC met.

### 3.5 TM05-62 — 3D → #38

- **3D toggle.**
  - `setTerrain` on the **hillshade's own Terrarium raster-dem source** (`encoding: "terrarium"`).
  - `maxPitch` 85, with exaggeration 1.4 from a token. Turning it off restores flat terrain, pitch 0 and the previous pitch limit.
- **Scrubber camera.**
  - Dragging the profile moves the camera behind and above the current point, looking 120 m ahead (pitch 68°).
  - Bearing comes from a 40 m Douglas-Peucker simplified copy of the line, circular-mean smoothed over ±250 m and eased between frames.
- **Fly the trail.**
  - Plays the same motion, ~45 s end to end, clamped to 60–400 m/s.
  - Grabbing the map pauses it. Reduced motion steps 500 m every 1.5 s instead of gliding.

All AC met. Browser check done headlessly; **smoothness still needs a real-browser look**
(§7).

---

## 4. Measured numbers

All measured 2026-10-02 on the local Docker PostGIS. It runs emulated on Apple Silicon,
so absolute times are pessimistic and the ratios are what matter.

### Distance queries (TM05-42)

The candidate set is the first 150 campsites by id in the Adirondack box, against all 76,551
water features. Times are the median of 5 warm runs of `EXPLAIN ANALYZE`
(`manage.py bench_distance`).

| Query | Units | Index on water? | Time |
|---|---|---|---|
| Before: KNN on 4326 | degrees | yes | **15.3 ms** (first cold run 61 ms) |
| Before: geography + ~1 km bbox prefilter | metres | prefilter only | **441 ms** |
| Before: geography + ~5 km bbox prefilter | metres | prefilter only | 2,515 ms |
| Before: geography, no prefilter | metres | **seq scan** | > 5 min (cancelled) |
| Rejected: geography GiST index + KNN | metres | yes | 406 ms |
| **After: KNN on `geom_m`** | **metres** | **yes** | **14.6 ms** |

- **Against the story's figures.** The story's 51 ms and 608 ms were for the same shapes; my first cold degree-KNN run was 61 ms, consistent with them.
- **Through the ORM.** 150 `nearest_distance_m()` calls took 217 ms; water plus trail took 365 ms.
- **Accuracy.** Compared with geodesic distance over all 1,276 sites whose nearest water is more than 1 m away: mean error **0.22%**, worst **0.55%**, largest absolute error **3.5 m**.
- **Datum mismatch.** PostGIS's PROJ and local GDAL disagree on the 4326→5070 datum step by **0.26 m**, so query points are transformed in the database.

### Scoring (TM05-43/44)

| Run | Time |
|---|---|
| 100 campsites, model 1.0.0, median of 3 warm | **934 ms** (9.3 ms/site) |
| All 1,320 campsites, model 1.0.0 | 18.1 s (13.7 ms/site) |
| Per factor, 100 sites | water 675 ms · trail 190 ms · legal 142 ms |
| 100 campsites, model 1.1.0 (weather), cold weather cache | 6.7 s — 5 Open-Meteo calls (5 grid cells) |
| 100 campsites, model 1.1.0, warm, median of 3 | **1,180 ms** (11.8 ms/site) |
| Weather analysis: miss → hit | 734 ms → **4.9 ms** |
| Score distribution, 1,320 sites (1.0.0) | min 0 · median 56 · max 98 |

### Route coverage (TM05-58)

Measured live on 2026-10-02 (`manage.py route_coverage`):

| Region | Relations (Overpass) | Ingested | Trail length on a route | Ways on a route |
|---|---|---|---|---|
| Adirondacks | 271 (5.0 MB, 8.1 s) | 270 (+1 super-relation skipped) | 1,318 of 11,143 km (**11.8%**) | 940 of 18,067 (5.2%) |
| White Mountains | 182 (3.0 MB, 38.2 s incl. two 504 retries) | 182 | 961 of 5,240 km (**18.3%**) | 583 of 7,596 (7.7%) |

- Three re-runs left the table at 452 rows, so the upsert is idempotent.
- Only 0.7% of unnamed Adirondack ways gain a name from a route. Named routes are the marked backbone, not the network.

### Gain calibration (TM05-59): Mount Marcy via Van Hoevenberg

| | Measured | Published | Error |
|---|---|---|---|
| Length (stitched main line) | 7.07 mi | ~7.4 mi | **−4.5%** |
| Gain, 100 m smoothing + 3 m threshold | 3,305 ft | 3,166 ft ("3,100+") | **+4.4%** |
| Gain, naive sum | 3,533 ft | 3,166 ft | +11.6% |
| Trailhead / summit | 2,187 / 5,340 ft | ~2,180 / 5,344 ft | +7 / −4 ft |

Across the sensitivity grid (25–400 m windows × 0–10 m thresholds), gain ranged from
3,159 to 3,533 ft. The defaults were chosen before calibrating and not fitted.

**Profile cost:**

| Route | Samples | First computation | Cached |
|---|---|---|---|
| Van Hoevenberg | 456 | 15.0 s → **3.8 s** after batching the sample reprojection | 7.8 ms |
| Northville-Placid (137 mi) | 2,001 (110 m spacing, capped) | 40.2 s | ms |

### Route API (TM05-60), median of 5 warm runs

| Request | Time | Size |
|---|---|---|
| List, High Peaks (67 routes) | 21 ms | 384 KB |
| List, High Peaks, `simplify=0.0001` | 33 ms | 141 KB |
| List, whole Adirondacks, simplified (200, truncated) | 234 ms | 752 KB |
| Detail, Van Hoevenberg, profile not cached | 5.7 s | 36 KB |
| Detail, Van Hoevenberg, cached (4 campsites) | **78 ms** | 36 KB |
| Detail, 2 km radius (13 campsites) | 183 ms | 57 KB |
| Detail, Northville-Placid, profile cached, weather cold (28 sites, 17 cells) | 11.7 s | — |
| Detail, Northville-Placid, warm | 1.26 s | — |

---

## 5. Judgment calls

**Phase 1**
1. **Projected column over geography index.** Measured 14.6 ms vs 406 ms, with ≤0.55% error. EPSG:5070 is CONUS-only, so Alaska will need EPSG:3338; this is documented under Known limitations.
2. **The candidate set** is the first 150 campsites by id inside the Adirondack box. The story's original 150 weren't recorded anywhere, so I fixed a reproducible set.
3. **Query points are transformed in PostGIS, not Python,** because of the 0.26 m PROJ mismatch.
4. **Public land gets no metric column.** Legal status is a containment question, so units don't affect it.
5. **Scoring weights** are water 0.35, legal 0.30, trail 0.20, weather 0.15, slope 0.10, land cover 0.05. They are relative weights, renormalised over the factors that count.
6. **Curves.** Water and trail both peak at 60 m (Leave No Trace's 200 ft). On the bank, water scores 35 and trail 50. Water halves every 400 m past the ideal, trail every 800 m. Search cut-offs are 3 km for water and 5 km for trail.
7. **Legal factor:**
   - Overlapping parcels use the most restrictive access.
   - Closed land caps the total at 0.
   - Outside every parcel scores 15 (`no_data`), not 0, because PAD-US is incomplete.
   - Scores: unknown access 40, restricted 45. GAP multipliers: 1.0 for GAP 1–2, 0.9 for GAP 3, 0.75 for GAP 4, 0.85 when unknown.
8. **Water candidates.** The 5 nearest of each flow class are scored, so a nearby wetland or intermittent stream can't hide better water.
9. **`not_available` vs `no_data`.** A missing source drops out of the total; "looked and found nothing" counts. This keeps a source outage from reading as a bad site.
10. **Weather is cached in the database for 1 hour and purged on expiry.** CLAUDE.md says weather is "never persisted", while the TM05-44 AC requires it to go through the cache. I reconciled the two as a short cache that is not a history, and rewrote the "Weather is a deliberate exception" section to say so.
11. **Weather details:**
    - The window is the issuing hour plus 3 days, on a 0.05° grid.
    - The fetch has a 5 s timeout and 2 attempts, failing fast because it sits on the scoring path.
    - It scores day 0 ("tonight").
    - Penalties: 4 per mm of rain (max 40); 1 per km/h of wind over 25 (max 30); 3 per °C below freezing (max 30).
12. **Gain reference.** I used 3,166 ft for "3,100+", the commonly cited figure, which is just above the net rise from trailhead to summit.
13. **TM05-41 skipped.** Its AC is unclear, and PR #31 already exists.

**Phase 2**

14. **Stack order.** TM05-58 and later stack on TM05-44, so the whole run is one linear stack. Routes need `geom_m`, and the route API needs scores and the cache.
15. **Routes ingest:** no tiling; side branches out of the length; super-relations skipped; whole routes stored even beyond the bbox.
16. **Stitching:** a 50 m join tolerance, and non-joining parts are left out rather than bridged.
17. **Profiles are computed on first request,** not precomputed for all 452 routes, which would mean thousands of 3DEP calls. I added a 2,000-sample cap after the Northville-Placid test. Precomputing the longest routes with `route_profile` is recommended.
18. **Route API:**
    - List: unnamed routes excluded, longest first.
    - Detail: at most 100 campsites, and the profile is computed synchronously on first request.
    - Campsite distance is measured to any route member; position is measured along the stitched line.
19. **Trail panel:**
    - Imperial units (US trails and published figures).
    - The score badge is deliberately **neutral**, because colouring is TM05-48's.
    - The panel docks right and hides the Saved panel via `:has()` while open; the map controls shift left.
    - Routes load at zoom ≥ 9.
20. **3D tuning:**
    - Same DEM source for hillshade and terrain; exaggeration 1.4.
    - Camera: pitch 68, zoom 14.6, 120 m look-ahead.
    - Bearing: 40 m simplification, ±250 m window.
    - Flythrough: ~45 s, clamped to 60–400 m/s. Play turns 3D on. Dragging the map pauses.

**Process deviations, stated plainly**

21. **TM05-59's story was created after I had started writing `elevation.py`,** though before anything was committed. Every other new story was created before work began.
22. **Two fixes landed on branches other than their own story's code:**
    - The per-point reprojection fix (15.0 s → 3.8 s) was found while timing TM05-60. I committed it as `TM05-59 …` on the TM05-59 branch and fast-forwarded TM05-60.
    - The 2,000-sample cap was found while testing TM05-61, and is committed there as `TM05-61 …`, although it changes TM05-59's code. Moving it would have needed a rebase and force-push of pushed branches with open PRs, which I avoided.
23. **This report's branch is keyed to TM05-42,** the first story of the run, because the report has no story of its own and I chose not to create a story for it.
24. **I started a Django dev server** (`runserver --noreload` on 127.0.0.1:8000) for the browser tests, because the one on 8000 had stopped. I stopped it at the end of the run. Your Vite dev server on 5173 was used read-only.

---

## 6. Every shared-file edit

Shared means files outside this run's own new modules.

| File | Edit | PR |
|---|---|---|
| `backend/pipeline/adapters/base.py` | `upsert_update_fields()` skips generated columns (PostgreSQL rejects writes to them) | #30 |
| `backend/geodata/models.py` | `METRIC_SRID`, `metric_geom()`, `geom_m` + GiST index on Campsite/Trail/WaterFeature; new `TrailRoute` model | #30, #34 |
| `backend/config/settings.py` | `+ "scoring"`, `+ "analysis"` in `INSTALLED_APPS` | #32, #33 |
| `pyproject.toml` | `+ "scoring"`, `+ "analysis"` in isort `known-first-party` | #32, #33 |
| `backend/pipeline/adapters/__init__.py` | import `osm_routes` (the documented registration step), docstring line | #34 |
| `backend/api/urls.py` | +1 import, +2 `path()` lines | #36 |
| `docs/architecture.md` | new sections (metres, analysis cache), weather exception rewritten, limitation replaced, table rows, code map | #30, #33, #34, #35 |
| `docs/pipeline.md`, `docs/api.md` | new sections for osm-routes and the route endpoints; "Not included yet" updated | #34, #36 |
| `frontend/src/pages/Discover.tsx` | +10 lines: `mapInstance` state set on load/cleared on unmount, `<TrailInsight map={mapInstance} />`, one-line `isRouteHit` guard in the click handler | #37 |
| `frontend/src/theme.css` | +19 lines route/chart tokens (#37), +4 lines `--map-terrain-exaggeration` (#38) | #37, #38 |
| `frontend/src/api.ts` | `const API_BASE_URL` → `export const API_BASE_URL` | #37 |

**Not touched:**
- `backend/accounts/`, any scoring endpoint (TM05-45/46)
- `frontend/src/map/popups.ts` and any score display or colouring (TM05-47/48)
- `.github/workflows/`, `docker-compose.yml`, deployment config (TM05-49/50)
- `CLAUDE.md` and `.env`

`frontend/src/map/layers.ts` is only *imported from* (`TERRAIN_SOURCE_ID`).

---

## 7. What to check by hand in the browser

With the stack checked out (or merged) and the backend running:

1. **Route click.** On `/discover`, zoom to the High Peaks (zoom ≥ 9): named routes appear as a faint pale line under the trails. Click one: the trail panel opens on the right, and **no** segment popup opens.
2. **Van Hoevenberg Trail.** The first open takes ~4–6 s ("Measuring the trail…"). Check: 7.1 mi, ~3,305 ft gain, high point ~5,340 ft, Naismith ≈ 3 h 55 min. Campsites list Marcy Dam near mi 2.3.
3. **Hover linking.** Chart hover moves the yellow marker on the map; moving over the highlighted route moves the chart cursor.
4. **Campsites.** Change "within" to 2 km: the list grows (13 for Van Hoevenberg). Click a campsite: the map flies to it.
5. **3D toggle.** The map pitches and the relief should look right (no spikes or noise). The camera sits behind the marker, looking along the trail.
6. **Scrubbing.** Drag along the profile. On a switchback-heavy stretch the camera should **turn** rather than whip.
7. **Fly the trail.** Smooth at ~45 s end to end in a real browser; this could not be judged headlessly. Grab the map mid-flight: it pauses. Close the panel: 3D turns off and the map is flat again.
8. **Reduced motion.** With OS reduced motion on, Fly steps every 1.5 s instead of gliding.
9. **Long route.** Northville-Placid (137 mi) takes up to ~40 s on first open (the message says so); after that it's instant.
10. **Unrelated popups.** Campsite, trail and water popups still work away from named routes.
11. **Panel overlap.** While the panel is open, the Saved panel (signed in) is hidden and the zoom/compass sit left of the panel.

---

## 8. Drafted teammate comments (not posted)

Ready to paste. All three refer to `docs/scoring.md` §1, "Output contract (version 1)".

### TM05-45 — Serve scored campsites through the API (Abdulrahman Shaalan)

> The scoring engine (TM05-43, PR #32) and the weather factor (TM05-44, PR #33) are up for
> review. Here is exactly how to consume them for this story. The full contract is in
> `docs/scoring.md` §1.
>
> **Calling it.** Load the config once per request and pass it in, rather than reloading it
> per site:
>
> ```python
> from scoring.config import load
> from scoring.engine import score_campsite, score_location
>
> config = load()
> result = score_campsite(campsite, config)   # or score_location(lon, lat, config)
> ```
>
> Both return a plain dict, so put it straight into the GeoJSON feature's `properties`. For
> example, `properties["score"] = result["score"]` and
> `properties["score_breakdown"] = result`. `/api/routes/<id>/` in #36 already does exactly
> this, if you want a reference.
>
> **Shape (real output, Marcy Dam, trimmed):**
>
> ```json
> {"contract": 1, "model_version": "1.1.0", "config_digest": "0a9724fd",
>  "location": {"lon": -73.951989, "lat": 44.158017}, "score": 69,
>  "factors": [
>    {"key": "water", "label": "Water", "status": "scored", "score": 98.4, "weight": 0.35,
>     "effective_weight": 0.35, "contribution": 34.4,
>     "measurement": {"distance_m": 69.6, "ideal_m": 60, "feature_type": "stream",
>                     "perennial": true, "name": null, "source": "nhd",
>                     "source_id": "115351701", "nearest_any_m": 0.0},
>     "explanation": "Perennial stream 70 m away (ideal is about 60 m). ..."},
>    {"key": "legal", "status": "no_data", "score": 15.0, ...},
>    {"key": "trail", "status": "scored", "score": 99.4, ...},
>    {"key": "weather", "status": "scored", "score": 65.8, ...},
>    {"key": "slope", "status": "not_available", "score": null, "effective_weight": 0.0, ...},
>    {"key": "land_cover", "status": "not_available", "score": null, ...}],
>  "caps": []}
> ```
>
> **Things that will bite:**
> - **Cost.** Scoring takes ~10 ms per site warm (100 sites ≈ 1.2 s). A cold weather cache
>   adds ~0.7 s per 0.05° grid cell; 100 Adirondack sites span 5 cells. Keep the existing
>   per-bbox cap and truncation (your AC), because scoring 6,000 features on demand would
>   take a minute.
> - **Don't cache longer than the weather.** Weather changes the score hourly, so any
>   response cache must be at most 1 hour and keyed on `model_version` + `config_digest`.
>   Your AC wants on-demand scoring anyway, which is right.
> - **Score 0 with good factors means a cap.** Land marked closed caps the score at 0.
>   Pass `caps` through so the frontend can say why. Real example: Wilderness Campground at
>   Heart Lake → `{"factor": "legal", "max_score": 0, "reason": "Inside land marked closed
>   to the public (Other Easement)."}`.
> - **Weather outages.** If Open-Meteo is down, the weather factor comes back
>   `not_available`. The score is still valid and simply excludes weather, so don't treat
>   this as an error.
> - **Invalid coordinates.** `score_location` raises `ScoringError` for out-of-range
>   coordinates. Map it to a 400.
> - **Low legal scores.** Expect most legal scores to be 15 ("probably private") until
>   TM05-57 repairs PAD-US geometry: only 199 of 1,320 sites currently fall inside a parcel.
>   That's a data gap, not a bug in your endpoint.

### TM05-47 — Show the score on the map (Sahaj Soni)

> The score contract you'll render is in `docs/scoring.md` §1 (PR #32). TM05-45 will put the
> whole result on each campsite feature as `properties.score` and
> `properties.score_breakdown`. What the popup needs:
>
> - **The headline** is `score` (an integer, 0–100). If `caps` is non-empty, show
>   `caps[0].reason` right under it. A 0 with great water is almost always "Inside land
>   marked closed to the public".
> - **Factor rows.** Iterate `factors` in order; never index by position, because more
>   factors will appear. For each row show `label`, `score` (one decimal, out of 100), and
>   `explanation`, which is already plain English: "Perennial stream 70 m away (ideal is
>   about 60 m)." If you'd rather build your own wording, the raw values are in
>   `measurement` (e.g. `measurement.distance_m`, `measurement.perennial`).
> - **Pending factors (your AC).** Use `status`:
>   - `scored` → normal row.
>   - `no_data` → it *was* evaluated and found nothing (no water within 3 km, not on public
>     land). Show the score; it's real and it counts.
>   - `not_available` → **show "pending" or "not available", never 0.** `score` is `null`
>     here. Slope and land cover are always this until Sprint 5, and weather is when
>     Open-Meteo is down.
> - **Why it scored that.** `contribution` is how many of the overall points each factor
>   supplied. The contributions add up to the score (±0.1), so a small bar per row
>   explains the number.
> - **Weather date.** The weather row is time-sensitive. Show `measurement.date` ("forecast
>   for 2026-10-02").
> - **Score can't be computed.** If `score_breakdown` is missing or the request failed,
>   fall back to the current name/type popup.
>
> The trail panel (#37) lists campsite scores with a deliberately neutral badge. Once you
> pick the colour system in TM05-48, it can reuse your tokens.

### TM05-48 — Colour campsites by score (Sahaj Soni)

> For colouring, you only need three fields per campsite from TM05-45: `properties.score`,
> `properties.score_breakdown.caps`, and the factor `status` values. Contract:
> `docs/scoring.md` §1.
>
> - **The value to colour by** is `score`, an integer 0–100. In MapLibre, a `step` or
>   `interpolate` expression on `["get", "score"]` works directly on the GeoJSON source.
> - **"No score" vs "low score" (your AC):**
>   - A site with no `score` property (scoring failed, or not yet served) has nothing to
>     read. Use `["has", "score"]` or a `coalesce` fallback to give it a distinct "unscored"
>     style, e.g. hollow, rather than the low end of the ramp.
>   - A site with `score: 0` and a non-empty `caps` is *legally closed*, not merely poor.
>     Consider its own treatment, e.g. a strike or outline. It's the one case where the
>     number alone misleads.
> - **The real distribution** is useful for choosing breakpoints. Across all 1,320
>   campsites today the range is 0–98 with a median of 56. Most sites sit in the 50s and
>   60s, partly because legal status reads "probably private" for most sites until
>   TM05-57 fixes PAD-US coverage. A ramp tuned to today's data will shift after that
>   lands, so prefer fixed breakpoints over percentiles.
> - **Scores move hourly.** Weather contributes up to 15 points, so a site's colour can
>   change from one hour to the next. Fixed breakpoints keep that drift readable.
> - **Avoid clashing with existing map colours.** The trail-insight work (#37/#38) adds
>   `--map-route` (pale) and `--map-route-selected` (yellow) to theme.css for named routes.
>   Avoid a yellow in your ramp that could be confused with the selected-route line.

---

## 9. Jira activity (complete list)

- **Transitioned To Do → In Progress:** TM05-42, -43, -44, -58, -59, -60, -61, -62.
  Nothing was moved to Done.
- **Created:**
  - TM05-57, backlog, 3 pts.
  - TM05-58 to TM05-62, Sprint 4, 5 pts each.
  - All assigned to Davis Stapleton, each with a description and AC in `customfield_10044`.
- **Comments:** one PR comment each on TM05-42, -43, -44, -58, -59, -60, -61, -62.
- **Not done:** no worklogs; no comments posted on TM05-45, -47 or -48 (drafts are in §8).
