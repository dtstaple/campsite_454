# TM05-170: natural-language trip finder

Captured 2026-11-15 by Davis Stapleton with headless Chrome (DevTools protocol) against
`npm run dev` and `manage.py runserver` on the local dev DB, signed out. The contract is
in `docs/api.md`, "Natural-language trip finder".

**Which reader ran.** No `ANTHROPIC_API_KEY` was set on this machine, so every request
here was read by the **keyword parser**, and the page says so. The model path is covered
by the mocked tests in `tests/test_discover_interpret.py`. The live check with a real key
is still to do: set `ANTHROPIC_API_KEY` in `.env`, restart the backend, and repeat.

## What was run (Discover trails, Adirondack Park, 270 trails before)

| Request | Size | Reading | Trails |
|---|---|---|---|
| "two nights, lakeside, moderate climb" | 1440 x 900, 390 x 844 | Moderate · campsites within 1,640 ft (500 m) · 2 nights · water view | 51 |
| the same, after removing the "Moderate" chip | both | campsites within 500 m · 2 nights · water view | 108 |
| "quiet overnight in the High Peaks, dog friendly, under 12 miles" | both | Adirondack Park · under 12 mi · campsites within 500 m · 1 night. Unsupported: crowding, dog rules | 101 |

The interpret request took 305–322 ms from click to chips, including the search.

- **Filter chips** (solid) narrow the trail search. Choose one to edit it in the Filters
  panel, or × to remove it.
- **Dashed chips** (nights, water view) are read from the request but are not trail
  filters. Each says why.
- **Unsupported asks** are named back: "Crowding isn't something we can measure yet."
- **The fallback note:** "The AI reader isn't set up here, so a simple keyword reader read
  your request. Check the chips."

## Screenshots

| File | Shows |
|---|---|
| `two-nights-lakeside-moderate-{1440,390}.png` | The box, "How I read your request", the fallback note, and the 51 results |
| `two-nights-lakeside-moderate-{1440,390}-chip-removed.png` | After × on "Moderate": 108 results, "Filters (1)" |
| `unsupported-asks-{1440,390}.png` | Unsupported asks named back |
