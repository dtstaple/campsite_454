# Potential campsites along a trail (TM05-99)

The trail panel's **Find campsites along this trail** answers "where could I spend the
night?" Hikers usually ask that before they ask "where has someone mapped a site?". It
shows two kinds of place, together, ordered by mile:

- **mapped campsites** near the route: the existing list (TM05-60), with legality verdicts
- **potential spots**: points the candidate search computed, labelled **"Potential spot
  (unverified)"**

Both appear on the map and in the list, and both have **+ Night**. Mapped campsites are
**off by default** in both modes, and stay one click away in the layer panel. Search
results draw even when the Campsites layer is off, because they belong to the trail
search.

## The search (`backend/planning/candidates.py`, config `backend/planning/candidates.yml`)

1. **Sample.** Every `sample_spacing_m` (200 m) along the trail's stitched line, a point
   at each of `offsets_m` (60, 120, 200, 300, 450, 700 and 1,000 m) to each side. Only
   offsets inside the user's corridor (the panel's **within**) are used.
2. **Hard filters.** A candidate must pass all of them. They run cheapest first, and a
   point is counted against the first one it fails:

   | Filter | Rule | How |
   |---|---|---|
   | `public_land` | Inside public land whose access is **open**. Where parcels overlap, the most restrictive access wins, as in the legal factor. | PostGIS `ST_Intersects` against PAD-US |
   | `trail` | At least **150 ft (45.72 m)** from *any* mapped trail | Indexed `ST_DWithin` on `geom_m` |
   | `water` | At least **150 ft** from any mapped water | Indexed `ST_DWithin` on `geom_m` |
   | `pooling` | **Not** inside a high water pooling risk zone from the terrain model (TM05-143, `reject_pooling_risk`). Checked only where `make terrain` has run for the trail's region; elsewhere every candidate's check reads "Water pooling risk not checked: no terrain data here yet." | Indexed `ST_Intersects` on the merged `pooling-risk` zones' `geom_m` |
   | `elevation` | Clear of the DEC limits encoded in TM05-76: 4,000 ft in the Adirondacks, and 3,500 ft in the High Peaks Wilderness. It needs the verdict's 50 ft margin **below** each limit; a point within the margin is rejected, not guessed. | One 3DEP sample per point |
   | `terrain` | 3DEP has elevation and slope there | The 3DEP sampler |
   | `slope` | At or below **5°** (`max_slope_deg`) | The campsites' 3×3 Horn stencil, 10 m apart (TM05-64), through the `site_terrain` cache |

   The 150 ft rule is NY's rule for camping anywhere other than a designated site
   (`designated_150` in `scoring/verdict.py`). Elevation is checked before slope because
   it costs one 3DEP sample per point, against nine for slope, and it removes most points
   on a High Peaks trail.
   **Terrain badges.** Each candidate carries `terrain`: `{"pooling", "shelter",
   "water_view"}`. A potential spot has no site-level terrain facts, only the zones
   (TM05-153 added `sheltered` and `damp-ground`; see step 4):
   - `shelter` is `exposed` (inside an exposure zone), `sheltered` (inside a sheltered
     zone), or `moderate` (in neither, once both layers exist).
   - `pooling` is `medium` (inside a damp-ground zone) or `low` (outside it). High was
     filtered out. Without the damp-ground layer it stays null.
   - `water_view` stays null: a viewshed per potential spot is too costly.

   Anything the zones can't decide stays null rather than guessed, and Find campsites'
   quick filters treat unknown as not matching.

   **Caching.** The cache key includes the latest finished terrain run, so a new
   `make terrain` re-filters cached searches.
3. **Score.** The best survivor at each sample station is scored with the existing
   engine (`score_location`), at most `max_scored` (60) of them, evenly along the trail.
   "Best" is the best terrain (step 4), then the flattest. Scoring costs about 0.1 s a
   point, and the spread keeps one per half mile anyway.
   **Weather is left out of the score**: it is tonight's forecast, and this answer is
   cached for 30 days.
4. **Rank on terrain (TM05-153).** The spots that passed **every** filter are ranked on
   the terrain zones, so the search prefers sheltered, dry, gentle ground, with a view
   when it can. Ranking comes after the filters and never touches them: it only orders
   points that already passed. Each factor in `ranking.factors` (candidates.yml) reads
   one zone layer. A point inside a zone of a listed class gets `weight × value` added to
   its score:

   | Factor | Zone layer (class) | Points | Reason shown |
   |---|---|---|---|
   | `shelter` | `sheltered` (DEV below −0.75) | +8 | Sheltered: lower than the ground around it |
   | `exposure` | `exposure` (`high`, DEV 1.0 and up) | −8 | Exposed: stands above the ground around it |
   | `damp` | `damp-ground` (`medium`, TWI 10 to 12.5) | −8 | Damp ground: water collects nearby |
   | `cold_air` | `cold-air` (`high` / `medium`), from TM05-147 | −8 / −4 | Frost hollow: cold air pools here |
   | `wind` | `wind-exposure` (`exposed` / `moderate`), from TM05-148 | −6 / −1.8 | Open to the prevailing wind |
   | `view` | `exposure` (`high`) | +3 | High ground: likely a view |

   - An exposed ridge nets −5: the likely view doesn't make up for the wind.
   - **A layer no run has written yet is not available.** It adds no points either way and
     shows no reason. So cold-air pooling and wind count as soon as TM05-147 and TM05-148
     write their layers (with these names and classes), and change nothing until then.
   - Where `make terrain` hasn't run for the region, nothing is ranked on terrain.
   - Every candidate carries `rank` (score plus terrain points) and `terrain_reasons`
     (`[{key, label, points}]`, best first). The trail panel's row shows a one-line summary
     ("Terrain +8: sheltered"), and the map popup lists each reason with its points.
5. **Spread.** Taking the highest rank first, a candidate is kept when it is at least
   `min_spacing_m` (805 m, about 0.5 mi) along the trail from every one already kept. At
   most `max_results` (8) are kept, and they're returned in mile order.

**Cache.** The answer, not the samples, is stored in the analysis cache (`trail_candidates`,
30 days). It is keyed by the route geometry, the corridor, this config and the scoring
config, so a second request for a trail is a lookup. Assembled trails (TM05-97) work the
same way.

## Honesty

- **Label and marker.** Every candidate is labelled "Potential spot (unverified)". On the
  map it is a **dashed ring** (`--candidate-*` tokens): hollow, so it is never mistaken
  for a mapped campsite (a solid circle). It never uses the score colours. In the list,
  its row has a dashed edge, and its score sits in a dashed box marked "Computed score".
- **Confidence.** Every candidate has the new **`computed`** confidence level
  (docs/confidence.md): not a record, and nobody has mapped a campsite there.
- **Detail popup.** Clicking a candidate shows its mile, distance off the trail, computed
  score, and **each check it passed**, with the measured values:
  - the parcel's name
  - the nearest trail and water
  - its elevation against the limit
  - its slope against the limit

  It also shows the DEC 150 ft rule, and says **"Road distance isn't checked; verify
  current rules on the ground."** Roads aren't in the data.
- **Empty result.** When nothing passes, the panel says why, naming the filter that
  removed the last points standing. For example: "No public land with gentle slope
  (≤ 5°) within 1 km of this trail." or "No public land with open access within 500 m of
  this trail."
- **As a night.** A candidate added as a night (plans, TM05-81) is stored by its position
  (`candidate/<lon>,<lat>`). It always carries the overnight-plan warning: "Night N,
  Potential spot (unverified): a computed spot, not a mapped campsite. It passed the public
  land, 150 ft, elevation and slope checks, but road distance isn't checked; verify current
  rules on the ground." On the map it is a numbered night marker with a dashed edge. In the
  plan GPX it is a waypoint with `<type>overnight-stop:unverified</type>`.

**Not checked:**
- distance from roads
- private inholdings PAD-US misses
- seasonal or local closures
- whether the ground is actually open: land cover isn't measured yet

## Measured (dev DB, 2026-10-08, corridor 500 m)

"Cold" means nothing cached: neither the search nor any 3DEP slope stencil for these
points. "Cached" is the second request.

| Trail | Ways | Sampled | public_land | trail | water | elevation | terrain | slope | Passed | Scored | Kept | Cold | Cached |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Cheney Pond-Irishtown (`way/1089777523`) | 1 | 650 | 60 | 5 | 75 | 0 | 0 | 420 | 90 | 44 | **8** | **32.3 s** | 4 ms |
| Deer Pond Trail (`way/556105759`) | 1 | 290 | 22 | 5 | 42 | 0 | 0 | 130 | 91 | 26 | **5** | **15.3 s** | 3 ms |
| Van Hoevenberg Trail (`relation/6619234`) | 32 | 570 | 44 | 71 | 44 | 207 | 0 | 173 | 31 | 13 | **3** | **19.2 s** | 3 ms |

The rejection columns count points removed by each filter, in order.

- **Where the cold time goes.** It is almost all 3DEP round trips: the elevation samples,
  then a 9-point slope stencil for each point that survives. The panel says so while it
  searches.
- **Van Hoevenberg.** The DEC limits remove 207 points, because the trail climbs Marcy,
  above 3,500 ft in the High Peaks Wilderness.
- **Cheney Pond and Deer Pond.** These sit low, so slope does most of the rejecting.

A browser run from the trail panel had the same results, plus 8 mapped campsites, merged
by mile, for Van Hoevenberg.
