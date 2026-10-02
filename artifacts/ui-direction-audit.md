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
| Q6 | Header docstring in `layers.ts` is two drafts pasted together: the first paragraph says "Extracted from App.tsx … fed by App's refresh()", the second says the same thing about Discover.tsx. The first is stale | `map/layers.ts` | touches a protected file |
| Q7 | `isort.known-first-party` lists `api` and `config` twice; ruff warns "One or more modules are part of multiple import sections, including: `api`" on every run | `pyproject.toml` | touches a protected file (Bleron, TM05-35) |
| Q8 | `source?.setData(collection as unknown as GeoJsonFeatureCollection)` — a double cast because `api.ts` declares its own `FeatureCollection` that adds `metadata`. Making the API type `extends GeoJSON.FeatureCollection` would remove the cast | `pages/Discover.tsx`, `api.ts` | safe, but deferred: it is a type refactor across files a teammate is likely to touch in TM05-47/48; noted, not changed |
| Q9 | Two oxlint `set-state-in-effect` warnings in `Discover.tsx` (`setSignInPrompt(false)` inside the session effect; `refresh()` on `enabled` change), plus `only-export-components` in `session.tsx` | frontend | safe in principle, but fixing either changes render timing, which the brief says cleanup must not do. Left alone and reported |
| Q10 | The campsite save button is built with `document.createElement` inside the map effect, with refs mirroring React state so it doesn't go stale. It works, but it is the most fragile code in the frontend. A React portal into the popup would remove the refs | `pages/Discover.tsx` + `map/popups.ts` | touches a protected file (popups) |
| Q11 | `api.ts` hardcodes `http://127.0.0.1:8000` as the fallback API base. That's fine for dev, but it should be documented next to `VITE_MAP_STYLE_URL` in `.env.example` | `api.ts` | note only |

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
