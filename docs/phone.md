# On a phone (TM05-103)

CampSite is used on the trail, so it has to work one-handed at phone width. Below
**640 px** (`PHONE_MAX_WIDTH` in `frontend/src/components/snaps.ts`) the layout changes.

## Bottom sheets

The trail panel and the campsite panel become **bottom sheets** (`components/Sheet.tsx`).
Each has a grip on its top edge, and snaps to one of three heights:

| Snap | Height (an iPhone 12–15, 390 × 844) |
|---|---|
| peek | 132 px: the trail's name, its live mile, and the start of the stats |
| half | half the map (about 405 px) |
| full | all but a 56 px strip of map at the top |

- **Drag** the grip to resize. A long drag settles on the nearest height, and a short fast
  **flick** moves one step.
- **Tap** the grip, or press Enter on it, to step peek → half → full → peek.
- The sheet publishes its height as `--sheet-height`, so the Location, Follow me and
  Map/Satellite buttons ride just above it.
- MapLibre's zoom and compass buttons are hidden while a sheet is open, since pinch-zoom
  and two-finger tilt replace them.
- The trail search spans the top, and its list starts folded. The layer panel starts
  folded too.

## Clear of the notch and the home bar

`index.html` sets `viewport-fit=cover`, and `src/phone.css` pads with
`env(safe-area-inset-*)`:
- the header clears the notch and the status bar
- the sheets clear the home bar
- the bottom-left buttons clear both the sheet and the home bar
- the Profile and Discover pages pad their sides

## Touch

- **Elevation scrubber:** it uses pointer events with pointer capture and
  `touch-action: none` (TM05-61), so a finger drag scrubs it the same as a mouse.
  Checked with emulated touch: dragging across the chart moved the readout to
  "mi 3.90, 3,319 ft, 23% grade" and the cursor marker along the trail.
- **The map:** pan, pinch-zoom and rotate are MapLibre's own touch handling.

## Live location

There are two buttons at the bottom left (`location/LiveLocation.tsx`):

- **Location** (◎) turns live GPS on and off. It shows a blue dot and an **accuracy
  circle** (the fix's reported accuracy, drawn as a metre-correct circle), and the button
  reads "±18 m".
  - It uses `watchPosition` with high accuracy.
  - It replaces TM05-78's MapLibre locate button: one location control, not two.
  - A successful fix clears TM05-78's remembered denial.
- **Follow me** (➤) keeps the map centred on each new fix, at zoom 15 or closer.
  Dragging the map turns it off, as in other map apps.
- **On the open trail**, within 150 m of it, the trail panel shows **"mi 2.1 along
  Van Hoevenberg Trail"** under its name, updated with each fix.

The position never leaves the browser.

## Add to Home Screen

There is a web app manifest (`public/manifest.webmanifest`): standalone display, start
URL `/discover`, and the dark theme colour. Icons:
- 192 and 512 px PNGs, and a maskable 512 px
- an SVG favicon
- an Apple touch icon at 180 px

All are drawn from `public/icon.svg` (a tent under a ridge, in the theme's base, accent
and text colours). **There is no offline support**: no service worker, so it needs a
connection like the website does.

## Testing on a real phone

Geolocation needs HTTPS. `make dev-phone` serves the app over HTTPS on the LAN; see
docs/setup.md, "Testing on a phone".

## Checked (2026-10-08, headless Chrome at 390 × 844, mobile, touch, 2× pixels)

- **No horizontal scroll** on the map or the Discover page. Cards are 358 px wide, one
  per row.
- **On first load:** the search bar is the full width (374 px), the trail list and
  layers are folded, and Location and Follow me sit above the Map/Satellite toggle,
  clear of the attribution.
- **Sheet snaps:**
  - opening Van Hoevenberg showed the sheet at **half** (405 px), with the zoom buttons
    hidden
  - a tap on the grip → **full** (753 px)
  - dragging it down → **peek** (132 px)
  - the buttons followed the sheet
- **Touch scrub** worked on the chart.
- **GPS** (emulated fix at Marcy Dam, ±18 m):
  - the dot and accuracy circle were drawn, the button read "±18 m", and the panel read
    "mi 2.1 along Van Hoevenberg Trail"
  - with **Follow me** on, a new fix 0.4 km on moved the map centre onto it, and the mile
    read "mi 2.5"
- **Manifest:** served, "standalone", 4 icons.
- **Errors:** none in the console.
- **Screenshots:** in `artifacts/tm05-103/`.

**Not checkable headless:**
- real safe-area insets: Chrome's emulation reports 0, so the notch padding is only
  verified on a device
- GPS accuracy outdoors
- iOS Add to Home Screen

The phone checklist in the run report covers these.
