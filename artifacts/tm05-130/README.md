# TM05-130: one set of breakpoints, and a tablet layout

Captured 2026-11-10 by Sahaj Soni with headless Chrome against `npm run dev`. There was no
backend, so the map shows the "Could not reach the API" banner. In the `map-trail-panel-*`
shots a placeholder `.panel.trail-panel` was added to the page, with the route planner
opened, to check the docked-panel layout.

| File | Viewport | What it shows |
|---|---|---|
| `map-390.png` | 390 x 844, phone | Phone layout, unchanged |
| `map-trail-panel-768.png` | 768 x 1024, tablet portrait | Layers folded on the left, search to the right of them, trail panel docked under the search, planner above the location buttons, one-line attribution |
| `map-trail-panel-844.png` | 844 x 390, large phone in landscape | Same lanes, compact planner |
| `map-trail-panel-1024.png` | 1024 x 768, tablet landscape | Same lanes |
| `map-trail-panel-1440.png` | 1440 x 900, desktop | Unchanged |
| `home-768.png` | 768 x 1024 | Home page in two even columns (it used to stack below 860px) |

## Desktop is unchanged

The bounding box of every overlay was dumped from `main` and from this branch: the header,
layer column, search, trail panel, route planner, location buttons, basemap toggle, map
controls and banner, plus every button, link and input. This was done at 390, 1280 and
1440 px, on `/discover` (with and without a trail panel), `/`, `/trails` and `/profile`.
The two dumps are identical, so the desktop and phone layouts did not move by a pixel.

## The breakpoints

`frontend/src/layout/breakpoints.ts` holds them:

- phone: up to 640 px
- tablet: 641–1279 px
- desktop: 1280 px and up
- short: up to 500 px tall

`frontend/tests/breakpoints.test.ts` fails the build if any stylesheet or `matchMedia()`
call uses another width or height query. The old one-off queries at 520, 720 and 860 px
are gone.
