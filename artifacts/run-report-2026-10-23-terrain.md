# Run report, 2026-10-23: Phase 0 bug fixes, and GeoLibre terrain intelligence

This covers one unattended run on Davis Stapleton's stories in Sprint 7. Every story went
To Do, then In Progress (and stayed there more than 5 minutes), then got a PR. Each PR was
merged after CI went green, and the story got a Jira comment with the PR link and a
summary. No worklogs were added, and nothing was moved to Done.

| Story | What | PR | Merged |
|---|---|---|---|
| TM05-137 | Route planner: forgiving snapping | [#104](https://github.com/dtstaple/campsite_454/pull/104) | yes, CI green |
| TM05-138 | Hike panel text on long trails | [#105](https://github.com/dtstaple/campsite_454/pull/105) | yes, CI green |
| TM05-139 (A) | Spike: GeoLibre terrain tools | [#106](https://github.com/dtstaple/campsite_454/pull/106) | yes, CI green |
| TM05-140 (B) | Vector tiles for trails, water, public land | [#107](https://github.com/dtstaple/campsite_454/pull/107) | yes, CI green |
| TM05-141 (C) | Adirondacks terrain pipeline | [#108](https://github.com/dtstaple/campsite_454/pull/108) | yes, CI green |
| TM05-142 (D) | Terrain insights in the app | [#109](https://github.com/dtstaple/campsite_454/pull/109) | yes, CI green |
| TM05-143 (E) | Terrain in scoring and search | [#110](https://github.com/dtstaple/campsite_454/pull/110) | yes, CI green |

- **Stories:** A–E were created in Sprint 7 (the active sprint), assigned to Davis
  Stapleton, with a description and AC (customfield_10044). Their points (2, 5, 8, 5, 3)
  were confirmed by reading back customfield_10016, the field TM05-42 uses.
- **The E deadline:** E merged on Fri 2026-10-23 at 23:28 ET, well before the Mon 2026-10-26
  22:00 ET cut-off, so it stays in Sprint 7.
- **Final state of main:** at 1144113, CI is green and the local gate passes:
  - ruff, ruff format, `makemigrations --check`: clean
  - pytest: 1,214 passed, coverage 94.61% (floor 93%)
  - frontend: lint, build, and 190 tests passed

---

## Phase 0

### TM05-137: forgiving routing (#104)

**Diagnosis.** The repro failed because the start's network (Big Pond Trail, 49 nodes,
42 km) joins the main network in OSM only through about 70 m of road: Blue Ridge Road
(secondary) and Branch Road (`service=driveway`). Neither was routable.

**Fix.**

- **Roads as connectors.** The graph now includes roads and sidewalks within 1 km of a
  trail (`osm-connectors`), at a 1.5× cost. A driveway is kept only if it touches a trail.
- **Bridged gaps.** Near-miss gaps of up to 15 m are bridged.
- **Snapping.** Points snap to segments within 1 km, choosing one connected piece. Small
  fragments carry a 300 m penalty.
- **Unconnected points.** These return a suggested nearby connected start.
- **Labels.** Road walks, tracks and bridged gaps are labelled in the route.

| Measure | Before | After |
|---|---|---|
| Graph components | 5,274 | 2,555 |
| Largest component | 813 km (7.3% of length) | 1,771 km (10.1% of 17,557 km) |
| 50 random pairs routed (seed 137) | 22% | 42% |
| Pairs with both ends on the main network | – | 18/18 (100%) |
| Repro route | fails | 34.0 km, routes |
| Warm routing (Loj / Upper Works / Hoffman) | 127 / 112 / 66 ms | 18 / 29 / 14 ms |
| Cold routing | about 0.4 s | about 0.8 s (graph load 0.93 s) |

**Failure breakdown** of 10 sampled failures:

| Cause | Count |
|---|---|
| Separate trail systems 5.9–25 km apart, with no road within 1 km of both | 7 |
| Saint Regis / Rail Trail, 1.5 km apart, with no link nearby | 2 |
| Across Lake Placid (0.6 km of water) | 1 |
| Snapping misses | 0 |

**Screenshots.** In `artifacts/routing-fix/` at 1440×900 and 390×844: the clicks, the
route, and the trail list with road walks and tracks labelled. The final re-check on main
is in `artifacts/terrain/final/`: the repro routes, 21.1 mi, with 0.1 mi of road walk and
0.5 mi of track labelled.

### TM05-138: hike panel text (#105)

- **The fix:**
  - Each distance carries its unit once ("0.4 of 137 mi"), with whole miles from 100 mi.
  - The glance row wraps instead of overlapping.
  - Long trail names break rather than pushing the status off-screen.
- **Tests:** pure-function tests (`frontend/tests/hikeGlance.test.ts`). The repo has no
  DOM test runner, so the layout was checked headless instead: no overlap and nothing
  clipped on the Northville-Placid Trail at both sizes.
- **Screenshots:** `artifacts/hike-panel/`, plus the final re-check in
  `artifacts/terrain/final/`.

---

## A: Spike, GeoLibre terrain tools (TM05-139, #106): AC met

**Decision: go.** GeoLibre runs server-side, and its licensing allows our use. Full detail
is in `docs/terrain-analysis.md`; raw runs are in `artifacts/terrain/spike/`.

- **Runs server-side.** geolibre-wasm 1.7.1 runs in-process under our Python 3.12 via
  wasmtime 49. With the compiled module cached, a call loads in 0.01 s. Slope over the
  Marcy Dam box matches `gdaldem` (mean 17.44° against 17.37°).
- **Licensing.**
  - The geolibre-wasm wrapper: MIT.
  - wasmtime: Apache-2.0 WITH LLVM-exception.
  - The WASM itself is built from geolibre-rust (MIT) and whitebox-wasm (Apache-2.0)
    using whitebox_next_gen's open crates (dual MIT/Apache-2.0). The proprietary Pro
    extension is external and not bundled.
  - All 1,062 tools report `license_tier: open`.
  - The runtime is pinned by SHA-256 and kept outside git.
- **Tools** (from listTools):
  - slope: `slope`
  - aspect: `aspect`
  - flow and TWI: `fill_depressions`, then `dinf_flow_accum`, then `wetness_index`;
    plus `depth_in_sink`
  - topographic position and exposure: `deviation_from_mean_elevation`
    (`relative_topographic_position`, `openness` and `geomorphons` were also measured)
  - viewshed: `viewshed`
  - zones: `reclass` and `raster_to_vector_polygons`
- **DEM source.** USGS 3DEP 1/3″ staged COG tiles from TNM's S3 bucket. Six tiles
  (2.58 GB) cover the region bbox, all verified live. The fallbacks, the 3DEP ImageServer
  `exportImage` and Terrarium, were verified live too.
- **Timings and memory** on the 3 km Marcy Dam box:
  - At 10 m, every candidate tool takes under 0.5 s and 26 MB, except
    `relative_topographic_position` (3.1 s) and `sky_view_factor` (6.9 s).
  - A 15 km box confirmed that cost scales linearly with cells.
  - The extrapolation to the whole region at 10 m and 30 m is in the doc.
- **The deciding limit.** Each call holds about 25 M cells: wasm32 can't make one
  allocation over 2 GiB.
  - A 30 m whole-region grid (57 M cells) can't even be read.
  - `breach_depressions_least_cost` panics at 45 m and at 60 m.
  - So whole-region hydrology runs at **45 m** with `fill_depressions`: 32 s, 1.3 GB.
- **Resolution per tool:**
  - hydrology: 45 m, whole region
  - sink depth, slope and aspect: 10 m, in tiles
  - DEV: 30 m, in tiles
  - per-site viewshed: 30 m over a 10 km radius, 0.27 s per site
- **New dependency:** `geolibre-wasm==1.7.1`, justified in PR #106 and in
  `requirements.txt`.

## B: Vector tiles (TM05-140, #107): AC met

- **Endpoint.** `/api/tiles/<layer>/<z>/<x>/<y>.mvt` builds each tile with PostGIS
  `ST_AsMVT` from a `TileLayer` registry. Each layer sets a minzoom, attribute sets per
  zoom, row thinning per zoom (water drops intermittent streams below z11) and
  half-pixel simplification.
- **Efficiency.** Geometry is clipped to the buffered tile before it is reprojected, which
  brought public-land tiles at z12–14 from 32 ms to 6–9 ms. Empty tiles are a 204, with
  `Cache-Control: public, max-age=3600, stale-while-revalidate=86400`, and responses are
  gzipped.
- **Adding a layer** is documented as three steps in `docs/api.md`. C used those steps for
  the two zone layers.
- **Map.** Trails, water and public land now draw from tiles. The caps and the
  "showing X of Y" notice are gone for those layers; campsites stay on the GeoJSON API.
- **Still works** (checked headless at both sizes; `artifacts/vector-tiles/`):
  - trail click opens the trail panel, via `source_id` as a tile attribute
  - water popups
  - 3D
  - both basemaps, with the satellite casings following their layers
  - layer toggles and camping mode
  - TM05-137 route planning
  - TM05-122's peaks and trailheads have no frontend layer yet, so there was nothing to
    break.
- **Measured:** medians of 3 sessions, from a fresh profile each time.

  | Session | Before | After |
  |---|---|---|
  | Adirondacks overview z8 | 651 KB, 1.68 s, 1,000 of 1,742 parcels | 442 KB, 0.46 s, all 1,742 |
  | High Peaks z12 | 98 KB, 1.23 s | 119 KB, 1.02 s |
  | Marcy Dam z15 | 173 KB, 0.46 s | 87 KB, 0.06 s |

- **Tests.** 19 backend tests decode every tile with a small MVT protobuf reader, so
  there is no new test dependency. They cover:
  - valid MVT
  - empty tiles
  - attributes per zoom
  - thinning and simplification
  - seams across tile edges
  - 404s and headers

  The frontend layer config is tested in `tileLayers.test.ts`.

## C: The terrain pipeline (TM05-141, #108): AC met

- **Registry.** `backend/terrain/tools.yml` holds:
  - the runtime pin (URL and sha256)
  - the DEM source
  - three grids: hydrology at 45 m whole-region, coarse at 30 m in tiles, fine at 10 m in
    tiles
  - six tools, each with its GeoLibre steps and its facts and/or zones
  - classification thresholds

  Loading validates references, sampling methods and class order, and names the tool when
  something is wrong.
- **`make terrain REGION=adirondacks`:**
  - checks or fetches the runtime
  - HEADs the 3DEP tiles, downloading only changed ones
  - builds a VRT and 30 m / 45 m mosaics, cached outside git and named by source digest
  - runs every tool tile by tile with overlap in spawned workers
  - runs per-site viewsheds
  - merges the zones and classifies every site
- **Per-site facts** for every Adirondack campsite:
  - pooling class with a reason
  - aspect, with facing and a sun label
  - shelter class with a reason
  - viewshed: visible area, main direction, and water view (viewshed ∩ NHD lakes within
    2 km), plus the outline
- **Zones:** pooling-risk (high) and exposure (high) polygons, served by B's endpoint.
- **Provenance.** A `TerrainRun` records tool versions, the runtime sha256, the DEM tiles
  with Last-Modified, `tools.yml`, per-tool CPU time, tasks and peak memory, coverage,
  zone counts, peak RSS and any failed sites.
- **Idempotent and resumable per tile.** This was shown on the real region: an
  interrupted run resumed with 118 of 130 tasks reused, and a finished run, run again,
  took 98 s.
- **make data / make refresh.** Each gained one step, `terrain`, after enrichment.
- **Measured** (fresh run, 3 workers, 743 campsites):

  | Item | Result |
  |---|---|
  | Tiles | 603 s wall, 1,714 CPU-s over 130 tasks |
  | Zone merge | 40 s |
  | Classify | 56 s |
  | Total | about 12 min with the DEM cached |
  | Peak WASM memory | 1,267 MB (hydrology); 10 m tiles under 580 MB |
  | Coverage | 99.9% for pooling, shelter, facing and viewshed; 97.7% for aspect (flat sites have none); 99.2% for TWI |
  | Zones | 16,676 pooling-risk and 18,715 exposure polygons |

  Per tool: wetness 93 s, sink 233 s, slope 346 s, aspect 297 s, position 56 s,
  viewshed 689 s. The one site with nothing is Iroquois Municipal Campground, which falls
  on nodata.
- **Tests,** 56 in `tests/test_terrain.py`, cover:
  - registry loading and errors, and adding a tool by config
  - thresholds
  - tile overlap with no seams: a neighbourhood filter computed in tiles equals the
    untiled result, and differs without the overlap
  - per-site fact mapping
  - an end-to-end run on a synthetic DEM with a fake GeoLibre
  - idempotent re-runs, resume after lost tiles, and `--fresh`
  - the WASM runner on a tiny WAT module
  - the 3DEP fetch, change detection, the offline fallback and the VRT

## D: Terrain insights in the app (TM05-142, #109): AC met

- **Campsite panel.** A Terrain section shows instantly with the panel. At Marcy Dam #5
  Lean-to it reads:
  - "Water pooling risk: Low. Water drains away from here (wetness index 7.2)."
  - "Faces southeast: morning and midday sun"
  - "Moderate shelter"
  - "View: 7.1 km², all around · water view"
  - the caveat: "Terrain-model estimate from bare-earth elevation. Trees, buildings and
    recent changes aren't counted."

  "Show what I can see" fetches `/api/campsites/<id>/viewshed/` and draws the outline.
- **Map.** "Water pooling risk" and "Exposure" toggles, with legends and the caveat. Each
  is a translucent fill with an outline, readable on both basemaps.
- **Find campsites rows** show the Water view, Sheltered and Pooling risk badges (and,
  after E, Exposed).
- **Styling.** Colours come only from new `--terrain-*` tokens in theme.css.
- **Checked.** Desktop and phone, in `artifacts/terrain/app/`. On the Phelps Trail, 8 of
  27 rows carry badges.
- **Tests:**
  - backend: the detail block with facts present, partial and missing; the viewshed
    endpoint; row badges
  - frontend (pure modules): panel wording for present, partial and missing facts;
    badges; the zone layer toggles

## E: Terrain in scoring and search (TM05-143, #110): AC met

- **Scoring: model 1.3.0, contract revision 1.2** (additive; new factor keys only):
  - `drainage`, weight 0.10: low 100 / medium 60 / high 10, the penalty
  - `shelter`, 0.05: 100 / 75 / 35
  - `view`, 0.05: a modest area curve, plus 20 for water in view

  The weights are in config.yml and appear in the explainable breakdown. Each factor reads
  the site's TerrainFacts at scoring time, so it is never stale after a terrain run.
  Where terrain hasn't run, the factors are not_available and drop out. Legality stays a
  separate gate, and a test asserts `legal_status` is unchanged. The Profile sliders gain
  the three factors.
- **Potential spots.** The new hard filter (`reject_pooling_risk`) skips high
  pooling-risk zones where terrain has run, and each candidate's checks say so.
  Candidates carry an "Exposed" badge when the zones support it. The cache key includes
  the latest terrain run.
- **Find campsites quick filters:** "Water view", "Sheltered" and "Low pooling risk".
  An unknown fact never matches.
- **Score distribution,** 743 sites, 1.2.0 → 1.3.0:

  | | Mean | Median | p10 | A/B/C/D/F |
  |---|---|---|---|---|
  | Before | 75.3 | 78 | 57 | 58/277/217/103/88 |
  | After | 76.0 | 79 | 61 | 39/297/231/124/52 |

  Per site, scores moved by −9 to +11.
- **What the pooling filter removed** on 3 trails (500 m corridor):
  - Phelps Trail: 0 of 630 sampled points
  - Calamity Brook Trail: 0 of 440
  - Deer Pond Trail: 1 of 290
  - shown results changed on none of them

  High pooling-risk ground lies along streams and wetlands, which the 150 ft water rule
  already excludes. Of the sampled points inside pooling zones, 1/1, 5/5 and 2/3 were
  within 150 ft of water.
- **Checked** (`artifacts/terrain/scoring/`):
  - Marcy Dam's breakdown: Drainage 100, Shelter 75, View 85.
  - Phelps Trail with Water view: 0 of 22 match, correctly, since it is a brook valley
    with no lake within 2 km. Sheltered: 8 of 22. Low pooling risk: 12 of 22.
  - Deer Pond Trail: 6 potential spots, each listing "✓ Not in a high water pooling risk
    zone". None is exposed, so none carries a badge.
- **Tests:** each factor, weights from config, the candidate filter (including skipped,
  off and all-wet cases), badges, the cache key, quick filters and sliders.

---

## Judgment calls

1. **Hydrology at 45 m with `fill_depressions`.** The spike's measured memory ceiling
   ruled out 30 m and breaching.
2. **A hollow alone is at most medium pooling risk.** Metre-deep "sinks" under
   campsites are DEM artefacts (culverts, flattened ponds). Without that rule, 28% of sites
   were "high"; with it, 7%.
3. **"Sheltered" is DEV below −0.75**, about 25% of sites, and **water view means 1 ha or
   more of lake within 2 km.** Over the full 10 km viewshed, bare earth "sees" a lake from
   77% of sites.
4. **Zones are not unioned or clustered.** For the dendritic pooling network, both ran
   past 10 minutes. Pieces are cut only at tile and chunk edges 75–112 km apart, and the
   fills draw seamlessly.
5. **GDAL cuts go through real temp files.** A `/vsimem/` warp leaves nodata blocks
   unwritten, and GeoLibre reads them as 0 m. That slowed `fill_depressions` from 11 s to
   over 10 minutes and would have corrupted edge values.
6. **The `classify` thresholds are outside the tile digest,** so tuning them recomputes no
   tiles.
7. **The terrain factors are never stored with the vector-factor results.** Enrichment
   runs before `make terrain`.
8. **Potential spots get only the badges the zones can support.** Their water view and
   low-versus-medium pooling risk stay null rather than guessed.
9. **Default terrain weights are small** (0.10 / 0.05 / 0.05). They nudge the score
   rather than reorder it.
10. **The viewshed is a separate request** (about 80 KB), fetched only on "Show what I can
    see".

## Edits to teammates' files

All are minimal, and each is in the PR that made it:

- `backend/pipeline/management/commands/refresh.py` (Bleron's):
  - `osm-connectors` and `trail-graph` (TM05-137, #104)
  - `terrain` (TM05-141, #108)

  Only routing-graph and terrain steps were added, as allowed.
- `tests/test_refresh_command.py` (Bleron's): the expectations for those steps
  (#104, #108).
- `frontend/src/profile/weights.ts` and `frontend/tests/weights.test.ts` (Abdulrahman's,
  TM05-115): the three terrain sliders and their fixtures (#110).
- `tests/test_api_campsite_layer_scores.py` (Abdulrahman's): the stored-keys expectation
  now subtracts `NOT_STORED` (#110).

Nothing in TM05-120, TM05-121, TM05-122, `backend/accounts/` or the Mobile Experience
backlog (TM05-130 to TM05-136) was touched. None of those stories had a branch on the
remote during this run.

---

## Adding terrain tools in Sprint 8

A tool is one entry in `backend/terrain/tools.yml`:

```yaml
tools:
  roughness:
    grid: coarse                      # hydrology (45 m, whole region) | coarse (30 m) | fine (10 m)
    steps:                            # GeoLibre calls in order; "{dem}" or "{<earlier step id>}"
      - {id: tri, tool: ruggedness_index, args: {input: "{dem}"}}
    facts:                            # sampled per campsite into TerrainFacts.values
      roughness: {sample: median, radius_m: 30}   # median | max | min | circular_mean
    zones:                            # optional: classified polygons as a tile layer
      layer: rough-ground
      classes: [{class: high, min: 2.5}]          # ascending
      min_area_m2: 50000
      simplify_m: 30
```

- **Facts:** the next `make terrain` samples them for every campsite, with no migration.
- **Zones:** also add a `TileLayer` in `backend/api/tiles.py`.
- **Classes:** a new class shown in the app or used in scoring needs a small mapper in
  `terrain/mappers.py`, plus a `TerrainFacts` column if it is filtered on.
- **Grids:** a grid's `overlap_m` must cover the widest neighbourhood its tools read.

`docs/terrain-analysis.md`, "The pipeline", has the full reference.

## Sprint 8 candidates

| Candidate | Output it would add |
|---|---|
| Cold-air pooling and frost hollows | Per-site "frost hollow" flag and a zone layer. `sky_view_factor` at 30 m combined with negative DEV and sink depth (all three measured in the spike; SVF costs about 89 CPU-min at 30 m). |
| Wind exposure by prevailing direction | `exposure_towards_wind_flux` per site, run for the prevailing westerly (270°) and a second sector: "exposed to the west wind". About 2.4 CPU-min at 30 m. |
| Solar hours | `solar_radiation` (Jun–Aug) as a per-site Wh/m² converted to "about N h of direct sun", replacing the aspect-only sun label. About 22 CPU-min at 30 m. |
| Trail-level terrain | Exposed-ridge and wet stretches along a route: sample the DEV and TWI rasters along each route profile into "2.1 mi above treeline-like exposure" and "0.4 mi of wet ground". This reuses C's mosaics. |
| Viewshed from any map point | An on-demand endpoint: one 30 m GeoLibre viewshed (0.27 s) on the cached mosaic, cached as an analysis answer. |
| Terrain-driven potential campsite generation | Seed TM05-99's candidate sampling from cells that pass flat + low pooling + moderate shelter, instead of fixed offsets, and add a "low pooling risk" class to candidates from the TWI raster. |
| Routing graph elevations from the DEM | Sample `build_trail_graph`'s edge elevations from C's cached 10 m VRT instead of 3DEP getSamples. A fresh build spent 660 s of its 895 s fetching 216,761 samples from 3DEP. Local GDAL sampling would take seconds, saving about 650 s (about 73%) per fresh build. Incremental rebuilds already reuse samples and would save only about 40 s. |
| Routing success-rate causes left unfixed (TM05-137) | Separate trail systems 5.9–25 km apart (7 of 10 sampled failures) need longer road walks than the 1 km connector radius; a "drive between trailheads" leg is the honest answer. Saint Regis / Rail Trail (2 of 10) needs a missing OSM link checked on the ground. Across Lake Placid (1 of 10) needs a water-crossing leg (canoe or boat) rather than a route. |
| Faster zone merge | A cross-tile union restricted to pieces that touch tile edges (the rest unchanged), to make zones fully seamless without the 10-minute union. |

## Housekeeping

- **The dev servers** started for the headless checks (Django on :8000, Vite on :5173) are
  stopped at the end of the run.
- **Data outside git.** The DEM tiles (2.4 GiB), mosaics and the WASM runtime stay in
  `~/.cache/campsite/terrain`. No DEMs, WASM, dumps or secrets were committed.
- **Not committed.** `docs/mobile-plan.md` remains untracked, as instructed.
