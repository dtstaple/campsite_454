# TM05-169: auto-plan overnight stops

Captured 2026-11-15 by Davis Stapleton with headless Chrome (DevTools protocol) against
`npm run dev` and the local dev DB (Adirondacks), signed in as a local check user. The
method and the contract are in `docs/routing.md` ("Auto-planning overnight stops") and
`docs/api.md` ("Auto-planned stops").

**One local workaround, not in the code.** On this dev DB, opening the Northville-Placid
Trail returned 500: the "terrain along the route" query (`terrain/along.py`, TM05-152) hits
a GEOS `TopologyException` on invalid terrain-zone geometry (100 invalid zones across four
layers). That is unrelated to this story and is reported in the Sprint 10 run report. For
these screenshots only, the dev server ran through a wrapper outside the repository that
answers `terrain_along` as "unavailable" when that error occurs. Nothing else differed.

## What was run

| Trail | Request | Size | Click to plan | Result |
|---|---|---|---|---|
| Northville-Placid Trail (137.4 mi) | 3 nights | 1440 x 900 | 2.7 s | 3 stops, no gaps |
| Northville-Placid Trail | 3 nights | 390 x 844 | 0.9 s | same plan |
| Phelps Trail (7.8 mi) | 1 night | 1440 x 900 | 3.6 s | 1 stop, no gaps |
| Phelps Trail | 1 night | 390 x 844 | 0.9 s | same plan |
| Northville-Placid Trail | 6 nights | both | 0.6–2.1 s | 5 stops, 1 gap reported |

The first request for a trail includes loading its elevation profile; later ones are
faster. The planner's own time on the server, measured in a Django shell: 575 ms for the
Northville-Placid Trail (61 mapped campsites, 52 Permitted), 183–226 ms for the Phelps
Trail (22 mapped, all Permitted, plus 5 cached potential spots).

**Northville-Placid, 3 nights** (an even day is 34.3 mi):

| Day | To | Distance | Gain | Loss | Why here |
|---|---|---|---|---|---|
| 1 | Mud Lake lean--to (as named in OSM) | 30.4 mi | 3,914 ft | 2,987 ft | Score 91: the highest-scoring of 4 legal stops between mi 24.0 and mi 44.7 |
| 2 | Campsite near Northville-Placid Trail | 33.6 mi | 3,613 ft | 2,889 ft | Score 90: the highest-scoring of 8 legal stops between mi 58.4 and mi 79.0; 2 other sites there are not confirmed legal |
| 3 | Catlin Bay #1 | 37.9 mi | 3,349 ft | 4,157 ft | Score 90: of 11 legal stops, Plumley's Point scores higher (91) but would make the days either side 44.4 and 29.0 mi |
| 4 | End | 35.5 mi | 2,920 ft | 2,831 ft | |

**Phelps Trail, 1 night:** Bushnell Falls Lean-to #1 at 4.8 mi (+1,331 ft), then 3.0 mi
(+2,073 ft) to the end. A higher-scoring site (86 against 82) would have made the days 2.9
and 4.9 mi with 770 ft of climb on day 1. The chosen stop splits the climb more evenly
(an even day climbs 1,702 ft).

**Northville-Placid, 6 nights:** "No legal stop between mi 33.4 and mi 45.1 for night 2,
so that night is left out and the days either side run together." The plan has 5 nights.

## Screenshots

| File | Shows |
|---|---|
| `northville-placid-3-nights-390.png` | The Auto-plan control (nights / miles a day) and the summary line, on a phone |
| `northville-placid-3-nights-{390,1440}-days.png` | The day table: distance, gain, loss, the verdict, and "Why here" under each stop |
| `northville-placid-6-nights-gap-{390,1440}-gaps.png` | A night with no legal stop, reported and not filled |
| `phelps-trail-1-night-{390,1440}-days.png` | Phelps Trail, 1 night |
| `phelps-trail-1-night-{390,1440}-saved.png` | The proposal saved as a normal plan, with Download plan GPX |
| `phelps-trail-1-night-{390,1440}-edited.png` | After + Night on another site by hand: 2 nights, and the reasons hidden because they no longer describe the plan |

**Editable plan.** After saving, the plan's GPX had 812 track points and 1
`overnight-stop` waypoint, fetched from `/api/plans/<id>/gpx/` in the same browser session.
