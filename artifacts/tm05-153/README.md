# TM05-153: terrain-driven potential campsites, before and after

Measured 2026-11-01 on the dev database, Adirondacks, corridor 500 m. "Before" is `main` at
`3536fa5`, and "after" is this branch, once `make terrain` had written the new `sheltered`
and `damp-ground` zones. Both runs call `find_candidates` directly for the same 3 trails.
The raw output is in `before.json` and `after.json`.

## The filters didn't change

The rejection counts are identical before and after on all 3 trails, so ranking only
reorders what the legality and setback rules already let through:

| Trail | public_land | trail | water | pooling | elevation | slope | Passed |
|---|---|---|---|---|---|---|---|
| Van Hoevenberg (11.4 km) | 44 | 71 | 43 | 0 | 208 | 173 | 31 |
| Phelps Trail (12.5 km) | 58 | 63 | 75 | 0 | 123 | 293 | 18 |
| Cheney Pond-Irishtown (12.8 km) | 60 | 5 | 75 | 7 | 0 | 417 | 86 |

## What the hiker sees

| Trail | Kept before → after | Same spot | Sheltered before → after | Damp or exposed kept |
|---|---|---|---|---|
| Van Hoevenberg | 3 → 3 | 2 | unknown → 1 of 3 | 0 |
| Phelps Trail | 6 → 5 | 2 | unknown → 2 of 5 | 0 |
| Cheney Pond-Irishtown | 8 → 8 | 5 | unknown → 6 of 8 | 0 |

- **Before:** every spot's shelter and pooling were unknown (`null`). The spots were the
  flattest at each station, ranked by score alone.
- **After:**
  - Each spot says what the zones know: sheltered, moderate or exposed, and low or medium
    pooling.
  - Sheltered spots are preferred: +8 each, shown as "Terrain +8: sheltered".
  - No kept spot is on damp or exposed ground.
- **Scores barely moved.** For example, Van Hoevenberg's first spot changed from score 98
  (exposure unknown) to a sheltered spot nearby with score 96, rank 104. The spots are
  still the best-scoring ground: ranking trades a point or two of score for shelter.
- **Phelps Trail kept 5, not 6.** Choosing the sheltered point at a station moved two
  picks closer than the 0.5 mi spacing, so one fewer fits. Mile 0.2 (score 83) and mile
  2.1 (score 82) dropped out. A sheltered spot at mile 1.3 (score 97) and one at mile 4.0
  (score 98) came in.
- **Speed:** cold searches took 6–14 s (Cheney Pond-Irishtown's 71 s "before" figure
  included first-time 3DEP fetches). Each zone layer adds one indexed query for all the
  surviving points.

## The terrain run behind it

`terrain-run.txt` is the first run with the two new tools. Postgres was killed for running
out of memory while inserting `damp`'s whole-region zone pieces in one statement. That led
to the fix in this branch: zone pieces are now inserted in batches of 2,000
(`ZONE_INSERT_BATCH`, `terrain/pipeline.py`).

`terrain-run-resume.txt` is the resumed run, which reused 131 of 140 tasks:

- 433 s, peak RSS 1.6 GB
- `damp`: 155 s, 1,267 MB WASM
- zones: `sheltered` 13,830 and `damp-ground` 32,050
- the existing `pooling-risk` (16,677) and `exposure` (18,715) layers are unchanged, apart
  from one pooling polygon

## In the app

`check-log.txt`, from headless Chrome at 1440 × 900 and 390 × 844 on Phelps Trail:

- candidate rows show "Terrain +8: sheltered" (2 of 5 rows)
- the map popup lists "+8 Sheltered: lower than the ground around it" under Terrain

Screenshots: `desktop-*.png`, `phone-*.png`.
