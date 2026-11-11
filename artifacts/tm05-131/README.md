# TM05-131: tap targets, and nothing hidden behind hover

Captured 2026-11-10 by Sahaj Soni with headless Chrome against `npm run dev`. Touch was
emulated through the DevTools protocol (`Emulation.setTouchEmulationEnabled`, which makes
`(pointer: coarse)` match). There was no backend, so the map shows the "Could not reach
the API" banner.

## Tap targets: every visible control is at least 44 x 44 px

An audit script measured every visible `button`, link, `input`, `select`, `summary`,
`[role=button]` and sheet handle. A checkbox counts through its `<label>`. Links inside
running text (the attribution, and the "Create an account" sentence on the home page)
are exempt under WCAG 2.5.8's inline exception.

| Page | 390 px (phone) | 1024 px (tablet) |
|---|---|---|
| `/discover` (map) | 22 controls, 0 under 44 px | 23 controls, 0 under |
| `/discover` + every trail/campsite panel button class | 42, 0 under | 43, 0 under |
| `/` | 7, 0 under | 7, 0 under |
| `/trails` | 8, 0 under | 8, 0 under |
| `/login` | 8, 0 under | 8, 0 under |
| `/register` | 9, 0 under | 9, 0 under |

The second row adds every button class the trail, campsite, plan, waypoint, viewshed and
profile panels use (`touch-panel-controls-*.png`), so it covers controls that only show
once data loads. Before the change, the map page at 1024 px had 28 of 28 controls under
44 px.

## Hover, by tap

Checked by dispatching real touch events:

- A tap on an element with a `title` opens a bubble with that text and outlines the
  element. A tap elsewhere, or a second tap, closes it.
- A tap on an enabled button (such as "Show your location") does what the button does,
  and no bubble opens.
- A mouse click never opens a bubble, so the desktop keeps the browser's own tooltip.

## Desktop unchanged

The bounding boxes of every overlay, button, link and input are identical between `main`
and this branch at 1280 and 1440 px, with no touch emulation. That holds on `/discover`
(with and without a trail panel), `/`, `/trails`, `/profile` and `/login`.
