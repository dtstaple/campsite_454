# Opening the map at the user's location (TM05-78)

The map page opens on the default region (the Adirondacks) at once. It then asks the
browser for the user's position, once, and moves when an answer comes back. If the user
has already started panning or zooming by then, the map stays where they put it.

| Answer | What happens |
|---|---|
| **Granted, inside a covered region** | The map centres on the user at zoom 12, with a blue dot at their position. |
| **Granted, outside every region** | The map centres on the user, so they can see there is nothing there, rather than being shown a region as if it were local. A notice at the bottom says so: "CampSite has no data where you are yet. The nearest covered region, White Mountains, is about 60 km away." It has a **Go to the White Mountains** link, which flies there. |
| **Denied** | The map stays on the default region. The denial is remembered in `localStorage` (`campsite.geolocation = denied`), so later loads don't ask again. |
| **Unavailable, or timed out after 10 s** | The map stays on the default region. Nothing is remembered, so the next load asks again. |
| **No geolocation at all** (an old browser, or plain HTTP) | The map stays on the default region. |

**Asking again.** MapLibre's locate button (bottom right, above zoom) asks on demand. A
successful locate clears the remembered denial. If the browser itself has blocked the
site, the button can't override that: the user unblocks it in the browser's site
settings.

**Covered regions.** These are the region boxes in `frontend/src/regions.ts`, which are
transcribed from `backend/pipeline/regions.yml`. "Nearest" is the shortest great-circle
distance to the edge of a region's box. Distances are shown rounded ("about 60 km"),
because the boxes are approximate ingestion extents.

**Privacy.** The position is used in the browser only, to move the camera and draw the
dot. It is never sent to the API or stored. Only the fact of a denial is stored.

**HTTPS.** Geolocation needs a secure context: HTTPS, or localhost in development. See
docs/deployment.md.

## Tests

- **Unit tests** in `frontend/tests/locate.test.ts`, using a fake `navigator.geolocation`:
  - inside coverage (Lake Placid)
  - outside coverage (Burlington VT, which is nearest the Adirondacks; Portland ME, nearest
    the White Mountains at about 60 km; Denver)
  - denied (remembered, and not asked again until cleared)
  - unavailable and timeout (not remembered)
  - no geolocation
  - storage that throws
- **Browser check** (2026-10-08, headless Chrome, with the position mocked through
  DevTools `Emulation.setGeolocationOverride` and the permission set through
  `Browser.setPermission`):
  - Lake Placid: centred at (-73.98, 44.28), zoom 12, dot, no notice.
  - Portland ME: centred there, with the notice naming the White Mountains, about 60 km
    away. "Go to the White Mountains" flew to (-71.48, 44.20).
  - Denied: stayed on the default region, and the denial was remembered. A reload didn't
    ask again.
  - Screenshots are in artifacts/tm05-78/.
