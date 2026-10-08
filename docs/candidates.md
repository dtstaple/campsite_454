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
   | `elevation` | Clear of the DEC limits encoded in TM05-76: 4,000 ft in the Adirondacks, and 3,500 ft in the High Peaks Wilderness. It needs the verdict's 50 ft margin **below** each limit; a point within the margin is rejected, not guessed. | One 3DEP sample per point |
   | `terrain` | 3DEP has elevation and slope there | The 3DEP sampler |
   | `slope` | At or below **5°** (`max_slope_deg`) | The campsites' 3×3 Horn stencil, 10 m apart (TM05-64), through the `site_terrain` cache |

   The 150 ft rule is NY's rule for camping anywhere other than a designated site
   (`designated_150` in `scoring/verdict.py`). Elevation is checked before slope because
   it costs one 3DEP sample per point, against nine for slope, and it removes most points
   on a High Peaks trail.
3. **Score.** The flattest survivor at each sample station is scored with the existing
   engine (`score_location`), at most `max_scored` (60) of them, evenly along the trail.
   Scoring costs about 0.1 s a point, and the next step keeps one per half mile anyway.
   **Weather is left out of the score**: it is tonight's forecast, and this answer is
   cached for 30 days.
4. **Spread.** Taking the highest score first, a candidate is kept when it is at least
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
