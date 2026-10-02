# UI direction audit — toward a map-first backcountry product

Branch: `TM05-XX-backcountry-ui-shell` · Audited from `main` at `d9b86a9` · 2026-10-01

This audit covers the current frontend and the parts of the backend that decide what the
frontend can show. It ends with a proposed roadmap built around one vertical slice:

> Map → Trail → Trail Details → Elevation Profile → Campsites Along Trail → Campsite Details

## 0. Files treated as protected during this run

Sprint 4 work is in flight, so these were read but **not modified**. Proposed changes to them
are collected at the end of this document.

| Area | Files | Why |
|---|---|---|
| Map layers and popups | `frontend/src/map/layers.ts`, `frontend/src/map/popups.ts` | Sahaj, TM05-47/48 |
| Scoring API and accounts | `backend/api/` scoring endpoints, `backend/accounts/` | Abdulrahman, TM05-45/46 |
| Infra | `.github/workflows/`, `docker-compose.yml`, deployment config | Bleron, TM05-49/50 |
| Scoring engine | any scoring code | Davis, TM05-42/43/44 |
| Touched by teammates in the last 7 days | `frontend/src/regions.ts` (Sahaj, TM05-31); `pyproject.toml`, `docs/setup.md`, `docs/onboarding.md`, `docs/deployment.md`, `tests/data_checks/*`, `backend/devdata/*` (Bleron, TM05-34/35); `docs/auth.md`, `tests/test_accounts_*` (Abdulrahman, TM05-32) | `git log --since="7 days ago" --name-only --all` |

`git branch -a` after `git fetch --prune` showed no Sprint 4 branches on the remote (only
Sprint 1–3 branches and `main`), so the list above is the instruction list plus the 7-day log.
`frontend/src/pages/Discover.tsx` and `frontend/src/App.css` were also touched by Sahaj in
TM05-30/31, but those changes are merged and this run's brief is about exactly those files, so
they were edited. That is a judgment call; see the summary.

---

## 1. Current UI architecture

### Components and routing

```
main.tsx            imports maplibre-gl.css (once), index.css, renders <App/>
└─ App.tsx          SessionProvider → BrowserRouter → .shell
   ├─ Header.tsx    brand, one nav link (Discover), sign in / account
   └─ Routes
      ├─ /          pages/Landing.tsx
      ├─ /login     pages/Login.tsx
      ├─ /register  pages/Register.tsx
      └─ /discover  pages/Discover.tsx   ← the map, 480 lines
```

`Discover.tsx` owns nearly everything on the map page: the MapLibre instance, the layer
toggles, the fetch/abort/debounce loop, the popup click handler (including a hand-built DOM
save button), the regions picker, the layers sidebar, the Saved panel and four kinds of banner.

### State

All map state is local `useState` in `Discover`:

- `enabled: Record<LayerName, boolean>` — the layer toggles, all `true` initially. Mirrored into
  `enabledRef` so the stable `refresh()` callback can read it.
- `meta` — per-layer response metadata (returned / matched / truncated), drives counts and the
  truncation banner.
- `zoom`, `center` — copied from the map on `moveend`/`zoomend`, used only for the zoom hints
  and to highlight the current region.
- `saved`, `signInPrompt`, `saveError` — saved campsites (server-backed via `saved.ts`), again
  mirrored into refs for the popup's DOM handler.
- Session comes from `session.tsx` (`SessionProvider`/`useSession`) backed by `auth.ts`
  localStorage token storage.

There is no global store, and nothing needs one yet.

### How map layers are wired

`map/layers.ts` declares the four layers as data (`LAYERS`), the `CLICKABLE` hit-order table,
and `addMapSources()`/`addMapLayers()`, called once on the map's `load`. Every source is a
GeoJSON source that starts `EMPTY` and is fed by `Discover.refresh()`. Paint values come from
`theme.css` custom properties via `theme.ts` (`mapColors()`, `mapPaint()`), because MapLibre
paint properties can't read `var(--x)`.

Visibility is **not** done with `setLayoutProperty('visibility')`. A layer that is toggled off
is simply not requested, and its source is set to `EMPTY`. That is why mode-driven visibility
(Phase 3) can be done entirely from `Discover` state without touching `layers.ts`.

The basemap is Stadia Alidade Smooth Dark (keyless on localhost), overridable with
`VITE_MAP_STYLE_URL`.

### Data fetching and caching (`api.ts`)

- One request per viewport to `/api/map-data/?bbox=…&simplify=…&layers=…`.
- The bbox is snapped outward to a grid of a quarter viewport span, so small pans produce
  identical requests.
- Responses are cached in a 40-entry in-memory LRU keyed by the query string.
- Linework (trails, water) is skipped below `MIN_ZOOM_FOR_LINEWORK = 9`; points and polygons
  are requested at any zoom.
- `refresh()` is debounced 400 ms after `moveend`/`zoomend` and aborts the previous request.

---

## 2. Code quality findings

| # | Finding | Where | Status |
|---|---|---|---|
| Q1 | Vite starter assets nothing imports: `src/assets/hero.png`, `src/assets/react.svg`, `src/assets/vite.svg`, `public/icons.svg` (the starter's social-icon sprite) | `frontend/` | **safe to fix now** |
| Q2 | `Discover.tsx` imports `../App.css`, which `App.tsx` already imports. The comment above it argues that CSS order matters, so a second import site is a liability | `pages/Discover.tsx` | **safe to fix now** |
| Q3 | `cacheStats()` and `clearCache()` are exported but have no callers | `api.ts` | **safe to fix now** |
| Q4 | `Discover.tsx` is 480 lines and renders four separate panels inline (regions, layers, saved, banners) | `pages/Discover.tsx` | **safe to fix now** (done as part of Phase 3b — the layers sidebar is being replaced anyway) |
| Q5 | `<title>frontend</title>` — the browser tab says "frontend" | `index.html` | **safe to fix now** (visible change, so done in Phase 3d rather than as "cleanup") |
| Q6 | Header docstring in `layers.ts` is two drafts pasted together: the first paragraph says "Extracted from App.tsx … fed by App's refresh()", the second says the same thing about Discover.tsx. The first is stale | `map/layers.ts` | touches a protected file — **fixed in follow-up** |
| Q7 | `isort.known-first-party` lists `api` and `config` twice; ruff warns "One or more modules are part of multiple import sections, including: `api`" on every run | `pyproject.toml` | touches a protected file (Bleron, TM05-35) — **fixed in follow-up** |
| Q8 | `source?.setData(collection as unknown as GeoJsonFeatureCollection)` — a double cast because `api.ts` declares its own `FeatureCollection` that adds `metadata`. Making the API type `extends GeoJSON.FeatureCollection` would remove the cast | `pages/Discover.tsx`, `api.ts` | safe, but deferred: it is a type refactor across files a teammate is likely to touch in TM05-47/48; noted, not changed |
| Q9 | Two oxlint `set-state-in-effect` warnings in `Discover.tsx` (`setSignInPrompt(false)` inside the session effect; `refresh()` on `enabled` change), plus `only-export-components` in `session.tsx` | frontend | safe in principle, but fixing either changes render timing, which the brief says cleanup must not do. Left alone and reported |
| Q10 | The campsite save button is built with `document.createElement` inside the map effect, with refs mirroring React state so it doesn't go stale. It works, but it is the most fragile code in the frontend. A React portal into the popup would remove the refs | `pages/Discover.tsx` + `map/popups.ts` | touches a protected file (popups) — **fixed in follow-up** |
| Q11 | `api.ts` hardcodes `http://127.0.0.1:8000` as the fallback API base. That's fine for dev, but it should be documented next to `VITE_MAP_STYLE_URL` in `.env.example` | `api.ts` | note only |
| Q12 | The `prefers-reduced-motion` block in `App.css` has a pasted copy of the `.status.cached` rule inside it, which is identical to the rule outside it and does nothing | `App.css` | **safe to fix now** |

No `any`, no `console.*`, no `TODO`/`FIXME`, and no `print()`/`breakpoint()` were found in
`frontend/src` or `backend/` (migrations excluded). Naming is consistent: kebab-case layer ids,
`LayerName` matches the API's layer keys. The theme discipline is good. `App.css` contains no
literal colours; every one comes from `theme.css`.

---

## 3. Readiness for a map-first, trail-centric product

### What already exists

| Need | Supported by | Notes |
|---|---|---|
| Trail geometry | `geodata.Trail.geom` (MultiLineString, 4326, indexed) | ~18k Adirondack trails after TM05-26 filtering |
| Routing graph | `Trail.osm_node_ids` (ordered) | Shared node IDs between ways are the graph edges. Nothing builds the graph yet |
| Trail length | `Trail.length_m` | Per OSM *way*, not per named trail |
| Trail name / type | `SourceRecord.name`, `Trail.trail_type` | Name is per way, and often blank |
| Campsites | `geodata.Campsite` (RIDB + OSM), `site_type`, `reservable`, `capacity` | Points, indexed |
| Water | `geodata.WaterFeature` | Lines and polygons, for distance-to-water |
| Legal status | `geodata.PublicLand` with `gap_status` and `access` | Background tint on the map |
| Viewport API | `/api/map-data/` | bbox + simplify + layer selection |
| Saved campsites | `accounts` saved-campsite endpoints | Keyed on `source_id` |
| Provenance | `geodata.IngestRun` | Per source/area run records |

### What's missing for the vertical slice

1. **Named trail routes.** `osm_trails.py` deliberately skips `route=hiking` relations (271
   over the Adirondacks). Its own comment calls this "a real gap for naming and for multi-day
   route planning", and notes it is recoverable without re-ingesting. Until relations are
   ingested, "a trail" in the UI means one OSM way segment, which is not what a hiker means.
2. **Trailheads.** Nothing ingests them. OSM has `highway=trailhead` nodes and
   `amenity=parking` + `hiking=yes`. RIDB facilities sometimes carry them.
3. **Elevation.** There is no DEM access at all. 3DEP is planned (CLAUDE.md §7, on-demand +
   cached). The frontend now has a *visual* hillshade (Phase 3c), but that is not data.
4. **Slope.** Derived from 3DEP. Needed for both the elevation profile and the campsite score.
5. **Trail ↔ campsite relationship.** There's no query for "campsites within N m of this
   trail", and no per-trail endpoint (`/api/trails/<id>/`), so the frontend can't open a trail
   as a first-class object.
6. **Feature ids are already in place.** `backend/api/layers.py` sets every layer's GeoJSON Feature
   `id` to `source_id`, trails included, so a trail-details route can key on the clicked
   feature's id with no API change.

---

## 4. Proposed roadmap

Estimates are Fibonacci suggestions for the team to re-point in planning.

### Sprint 5 — make "a trail" a real object

| Story | Owner | Pts | Slice step |
|---|---|---|---|
| Ingest OSM `route=hiking` relations into a `TrailRoute` model (name, ref, operator, ordered member ways, merged geometry, total length) with idempotent upsert and provenance | Davis Stapleton | 8 | Trail |
| `GET /api/trails/<source_id>/` and `GET /api/routes/<id>/`: detail with name, length, type, member segments, bbox | Abdulrahman Shaalan | 5 | Trail Details |
| `GET /api/trails/<id>/campsites/?within_m=`: campsites within a buffer of a trail, ordered by position along the line (`ST_LineLocatePoint`) | Abdulrahman Shaalan | 5 | Campsites Along Trail |
| Trail details panel: clicking a trail opens a compact floating panel (name, length, type, nearby campsites list) instead of only a popup; selected trail highlighted on the map | Sahaj Soni | 5 | Trail Details |
| Campsites-along-trail list in the trail panel, linked to markers; selecting one opens campsite details | Sahaj Soni | 3 | Campsites Along Trail |
| Ingest trailheads (OSM `highway=trailhead` + parking tagged for hiking) as a new adapter on the existing framework | Davis Stapleton | 3 | Map |
| Index/perf pass for the new spatial queries; add a seeded routes sample to `devdata` so CI and dev have route data | Bleron Balidemaj | 3 | — |

### Sprint 6 — elevation

| Story | Owner | Pts | Slice step |
|---|---|---|---|
| 3DEP client: windowed COG reads for a line or point set, cached answer with provenance (no pixels stored) | Davis Stapleton | 8 | Elevation Profile |
| `GET /api/trails/<id>/profile/`: sampled distance/elevation pairs, gain/loss, max grade | Abdulrahman Shaalan | 5 | Elevation Profile |
| Elevation profile chart in the trail panel, with hover synced to a map marker | Sahaj Soni | 5 | Elevation Profile |
| Slope per campsite from 3DEP, wired into the score's slope factor | Davis Stapleton | 5 | Campsite Details |
| Cache storage and eviction for derived raster answers; document ops runbook | Bleron Balidemaj | 3 | — |

### Later

- Campsite details as a full panel with the factor-by-factor score breakdown (needs the
  TM05-42/43/44 scoring work to land). Sahaj builds the panel, Abdulrahman exposes the
  breakdown.
- Trip planning: route between campsites over the `osm_node_ids` graph (Davis builds the
  graph, Abdulrahman the API, Sahaj the itinerary view).
- Backcountry Ski mode: the mode is already defined but disabled. It needs slope-angle shading
  (3DEP) and avalanche-relevant layers before it's worth enabling.
- West Coast and Alaska regions as config entries (Bleron for ingest ops, Davis for adapter
  tuning; note that Alaska's OSM coverage is sparse).
- Self-hosted or cached terrain tiles if the public terrain tile source becomes a reliability
  or rate concern (Bleron).

---

## Overnight run summary

Branch `TM05-XX-backcountry-ui-shell`, 11 commits on top of `main` at `d9b86a9`. The full
gate (`ruff check . && ruff format --check . && pytest`, then `npm run lint && npm run build`)
was run before every commit and passed every time: 440 passed, 10 deselected; lint 0 errors.
No change needed a revert. The three oxlint warnings that remain were all on `main` before this
run (see Q9).

### Completed

| Phase | What | Commit subject |
|---|---|---|
| 1 | This audit | `TM05-XX add UI direction audit …` |
| 2 | Removed unreferenced starter assets (Q1) | `… remove unreferenced Vite starter assets` |
| 2 | Removed the duplicate `App.css` import in `Discover.tsx` (Q2) | `… drop the duplicate App.css import …` |
| 2 | Removed the unused `cacheStats`/`clearCache` exports (Q3) | `… remove the unused cacheStats …` |
| 2 | Removed the duplicated rule in the reduced-motion block (Q12) | `… remove a duplicated rule …` |
| 3a | `frontend/src/modes/`: `modes.ts` (typed config), `icons.tsx` (original SVGs), `ModeSwitcher.tsx`. Hiking is the default; Camping is enabled; Backcountry Ski is `enabled: false` and never rendered | `… add activity modes …` |
| 3b | `components/LayerPanel.tsx` (floating, collapsible, mode-ordered, primary layer emphasised, quiet counts, regions inside), `components/SavedPanel.tsx` (extracted), `modes/visibility.ts` (later folded into `layers.ts`/`modes.ts`) | `… replace the map sidebar …` |
| 3c | `map/terrain.ts` (later moved into `layers.ts` as `addTerrainLayers()`): hillshade from a keyless raster-dem source, a Terrain shading toggle, `--map-hillshade-*` tokens | `… add terrain hillshade …` |
| 3d | Slim header on `/discover`; zoom and compass in a floating group at the bottom right; `--shadow-panel` and `--bg-floating` elevation on all chrome; the zoom-in notice is now a quiet pill; the tab title says CampSite | `… polish the map shell …` |
| 3e | Landing copy reframed ("Backcountry exploration" / "Find where to spend the night." / "Explore the map"), same structure | `… reframe the landing copy …` |

`Discover.tsx` went from 480 to 442 lines, despite gaining mode and terrain state.

### Hillshade source: verification record

- **URL:** `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png` (AWS Terrain
  Tiles / Tilezen Joerd, AWS Open Data registry). No API key.
- **Encoding:** `"terrarium"`, set explicitly in `addTerrainLayers()` in `map/layers.ts`. `tileSize: 256`, `maxzoom: 15`.
- **Verification (curl, 2026-10-01):** three tiles, all `200 image/png`, all 256×256 8-bit RGB
  PNGs, all with different MD5s, so none is a placeholder. I decoded them with the Terrarium
  formula `(R·256 + G + B/256) − 32768` to confirm the encoding:
  - Adirondacks z10/301/371: max **1600 m**. Mt Marcy is 1629 m.
  - White Mountains z12/1236/1485: max **1916 m**. Mt Washington is 1917 m.
  - Pacific z6/7/32: −4895 to −1575 m (ocean floor).

  Decoding the same tiles as Mapbox RGB would have given nonsense values, which confirms the
  encoding is right.
- **CORS:** with `Origin: http://localhost:5173`, the response carries
  `Access-Control-Allow-Origin: *`. WebGL needs that to read DEM pixels.
- **Attribution:** added on the source ("Terrain: Mapzen, USGS 3DEP and others", linking to the
  Joerd attribution doc).

### Skipped

- **No frontend unit tests.** The frontend has no test runner, and adding Vitest would be a new
  dependency the brief says to avoid unless clearly necessary. The `modes` config is checked by
  `tsc` in `npm run build`, but `orderedLayers`/`modeById` would be the first things to test if
  a runner is added.
- **Q8 and Q9 were not fixed** (Q10 was, in the follow-up). They're either type refactors across shared files or
  render-timing changes, which a behaviour-neutral cleanup shouldn't make.
- **No new dependencies.** None were added.

### Judgment calls

1. **The issue key is the literal `TM05-XX`.** I didn't guess a real issue number, because a
   wrong key would link this work to someone else's story. **Before opening the PR, create or
   pick the real story and rename the branch.** Commits with `TM05-XX` won't link in Jira. A
   squash-merge titled with the real key is the least invasive fix, since rewriting history
   would mean a force-push.
2. **I edited `Discover.tsx` and `App.css` even though Sahaj touched them in TM05-30/31.**
   Those changes are merged, no Sprint 4 branch exists on the remote, and the brief is
   specifically about these files. `regions.ts`, which Sahaj also touched, was left alone; the
   layer panel only reads `REGIONS`.
3. **Switching mode resets all layer toggles to that mode's defaults.** Manual toggles aren't
   remembered per mode, and the mode isn't persisted across reloads. Hiking is always the
   starting mode.
4. **Terrain shading is a mode-level `terrain: boolean`, not a `LayerName`.** It's a raster the
   map fetches itself, not an API layer, so it doesn't go through `refresh()` or `meta`. It is
   shown and hidden with `setLayoutProperty('visibility')`.
5. **The hillshade sits beneath the basemap's first symbol layer.** It is added before our data
   layers, so it ends up under the labels and under public land, water, trails and campsites,
   and `layers.ts` needed no edit.
6. **Count and zoom hint wording.** The zoom hint now reads `zoom 9+` instead of `z9+`. The
   loading spinner moved from the panel footer into the panel header, so it's visible when the
   panel is collapsed.
7. **Control placement.** Zoom and compass moved to the bottom right, and the Saved panel moved
   from the bottom left to the top right, where the controls used to be.
8. **New tokens in `theme.css`:** `--opacity-quiet`, `--radius-pill`, `--shadow-panel`,
   `--bg-floating`, `--blur-floating`, and `--map-hillshade-{shadow,highlight,accent,exaggeration}`.
   `theme.ts` gained `mapHillshade()`, with literal fallbacks matching the existing
   `mapColors()` idiom.
9. **The landing lede now names the White Mountains alongside the Adirondacks,** because
   `regions.ts` lists both as ingested.

### Proposed changes to protected files (not made overnight; see the follow-up below)

- **`frontend/src/map/layers.ts`** (Sahaj):
  - Delete the stale first paragraph of the header docstring (Q6).
  - Consider moving `orderedLayers()` from `modes/visibility.ts` next to `LAYERS`, so layer
    order has one home.
  - Optionally register the hillshade in `addMapLayers()` (or a sibling
    `addTerrainLayers()`) so all layer creation lives in one module. If so, keep the
    `firstSymbolLayerId` insertion point and the explicit `encoding: "terrarium"`.
  - For mode-specific *paint* emphasis (e.g. thicker trails in Hiking, larger campsite markers
    in Camping), `layers.ts` would need to export a `setModeEmphasis(map, mode)` that calls
    `setPaintProperty`. Nothing in this run needed it.
- **`frontend/src/map/popups.ts`** (Sahaj): move the campsite save button into the popup as a
  React portal, so `Discover` can drop `sessionRef`/`savedRef` (Q10). The new floating panels
  use `--bg-floating`/`--shadow-panel`; restyling `.maplibregl-popup-content` the same way
  would make popups match. That rule lives in `App.css`, so it isn't strictly protected, but it
  was left alone so it lands with the popup work.
- **`pyproject.toml`** (Bleron): deduplicate `known-first-party` (Q7) to silence ruff's
  "multiple import sections" warning.
- **`backend/api/`** (Abdulrahman): the Sprint 5 endpoints in the roadmap
  (`/api/trails/<id>/`, `/api/trails/<id>/campsites/`). No changes made.

### What to check in the browser

1. **`/discover` opens in Hiking:** campsites are unchecked and absent from the map; trails,
   water, public land and terrain shading are on.
2. **Switching to Camping:** campsites appear and are listed first and in bold. Switching back
   to Hiking hides them again.
3. **Only Hiking and Camping appear.** No Backcountry Ski anywhere.
4. **The hillshade looks like relief, not noise.** In the High Peaks (Adirondacks shortcut,
   zoom ~11–12) ridges should be lit from the northwest. Basemap labels should sit above the
   shading, and trails and water above both. Toggle Terrain shading off and on. This was the
   one thing headless Chrome couldn't confirm: it rendered the UI chrome, but not the map
   canvas, in virtual-time mode.
5. **Shading strength against the public land tint:** if it's too strong, lower
   `--map-hillshade-exaggeration` (0.45) or `--map-hillshade-shadow` alpha.
6. **Zoom and compass at the bottom right:** compass rotates with right-drag and resets on
   click. Attribution is still visible and includes the terrain credit.
7. **The header on `/discover` is a slim strip;** on `/` it's the normal header.
8. **Collapsing the Layers panel** with its header leaves the spinner visible while loading.
9. **Saved panel (signed in) at the top right;** clicking a row flies to the site and × unsaves.
10. **Zoom far out over the Adirondacks** so a layer truncates: the notice should be a small
    pill at the bottom centre. If the "Sign in to save campsites" banner is also showing, the
    two may sit close together at the bottom; check they don't overlap.
11. **Popups and the Save button still work** on campsites, trails and water.
12. **Landing page copy,** and the "Explore the map" button.

---

## Follow-up: protected-file proposals implemented

After the overnight run, Davis asked for the proposals above to be implemented. All were run
through the same gate before each commit, and it passed every time.

| Proposal | Done | Commit subject |
|---|---|---|
| `pyproject.toml`: deduplicate `known-first-party` (Q7) | Yes. The ruff "multiple import sections" warning is gone | `… deduplicate known-first-party …` |
| `layers.ts`: drop the stale docstring paragraph (Q6) | Yes | `… move layer ordering into layers.ts …` |
| `layers.ts`: move `orderedLayers()` beside `LAYERS` | Yes. `primaryLayer()` moved into `modes.ts`; `modes/visibility.ts` deleted | same |
| `layers.ts`: register the hillshade there | Yes, as `addTerrainLayers()` / `setHillshadeVisible()`; `map/terrain.ts` deleted. Same URL, `terrarium` encoding and insertion point | `… register the terrain hillshade in layers.ts` |
| `popups.ts`: save button as a React portal (Q10) | Yes. `popupContent()` returns the node plus a campsite actions slot; `components/SaveButton.tsx` is portalled into it; `sessionRef`/`savedRef` and the hand-built listener are gone; `popupFor()` is internal | `… render the popup save button through a React portal` |
| Popups on the floating surface tokens | Yes | `… match popups to the floating chrome …` |
| `layers.ts`: `setModeEmphasis()` for per-mode paint | **No.** The proposal said it would only be needed for per-mode paint, and nothing uses that yet; adding it would be dead code | — |
| `backend/api/` trail endpoints | **No.** Those are Sprint 5 roadmap stories for Abdulrahman Shaalan, not cleanups | — |

### Browser verification (headless Chrome over CDP, against the dev server and live backend)

- `/discover` opens in Hiking: Campsites unchecked; Trails, Water, Public land and Terrain
  shading checked.
- Switching to Camping: Campsites becomes checked and is listed first; counts load (151
  campsites, 2,043 trails, 2,500 / 9,668 water).
- Only Hiking and Camping are rendered.
- The hillshade renders as real relief, not noise: ridges are lit from the northwest and sit
  under the basemap labels. The attribution shows the terrain credit.
- Clicking Lake Durant Campground opens a popup with the portalled **Save** button. Clicking
  it while signed out shows "Sign in to save campsites". Closing the popup removes the
  button (0 left in the DOM).
- The screenshot showed the zoom-in pill cut off with an ellipsis and touching the
  attribution strip. Both are fixed: the pill now sizes to its content and sits higher, and
  the sign-in banner sits above it.

**Not verified:** the signed-in save/unsave round trip. It would have meant creating a test
account in your database. Sign in and save one campsite from a popup and from the Saved panel
to confirm it.
