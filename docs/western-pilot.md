# Western USA pilot: the Colorado Front Range (TM05-173)

The first region outside the Northeast. It is a **minimal pilot**: one small box, the
existing US data sources unchanged, and only camping rules quoted from official pages.
It shows that a Western region is a config change and nothing else, and it records what
that change does and doesn't give you.

## The region

| | |
|---|---|
| Key | `front-range-co` (`backend/pipeline/regions.yml`) |
| Label | Colorado Front Range (Indian Peaks) |
| Bbox | `[-105.70, 40.02, -105.52, 40.12]`, about 15 × 11 km |
| Covers | Brainard Lake Recreation Area and the eastern Indian Peaks Wilderness, Boulder Ranger District, Arapaho and Roosevelt National Forests |
| 3DEP tiles | one, `n41w106` (the box is inside a single 1° × 1° tile) |
| Region picker | "Front Range (CO)", in `frontend/src/regions.ts` |

The box stops short of Rocky Mountain National Park to the north, whose rules are not
configured. It is deliberately small so that the ingests and the terrain download stay
small.

## Sources

Nothing new: the same adapters as the Northeast, all of which are US-wide.

| Source | What it gave the pilot |
|---|---|
| PAD-US (USGS, ArcGIS feature service) | 30 parcels, including Indian Peaks Wilderness and Roosevelt National Forest |
| NHD flowlines / waterbodies | 903 / 167 |
| OSM trails | 188 |
| OSM campsites | 2 (Pawnee Campground; Ruby Gulch Dispersed Camping, just east of the box edge) |
| OSM landmarks | 29 |
| OSM routes (relations) | 0 |
| OSM connectors | 67 |
| RIDB (Recreation.gov) | **not run**: `RIDB_API_KEY` is empty in the local `.env`, so `make data` skipped it |
| 3DEP 1/3″ (terrain) | tile `n41w106`; see `docs/terrain-analysis.md`, "The Colorado Front Range pilot" |

## Camping rules

`backend/scoring/legality.yml`, entry `front-range-co`. The full list, with the quotes,
is in `docs/scoring.md` ("The Colorado Front Range pilot"). In short:

- **Checked:** "Campsites must be located at least 100' away from all lakes, streams &
  trails", on land PAD-US names Indian Peaks Wilderness. A site inside it is **Unknown**,
  citing the rule.
- **Cited for every undesignated site:** the designated-sites-only zones rule.
- **Cited, not checkable:** the June 1 – Sept 15 permit, the Four Lakes zone closure, the
  designated-site-only zones, and Brainard Lake's two seasonal rules.
- **Not configured, because they were not verified on an official page:** any elevation
  or treeline limit, campfire rules (they don't decide where you may camp), designated-site
  operators.

Sources, fetched 2026-11-17:
- [Indian Peaks Wilderness](https://www.fs.usda.gov/r02/arp/recreation/indian-peaks-wilderness)
- [Brainard Lake Recreation Area](https://www.fs.usda.gov/r02/arp/recreation/brainard-lake-recreation-area)

**Result on the pilot data:** both campsites are **Unknown**. Pawnee Campground is on
Roosevelt National Forest land and cites the designated-zones rule. Ruby Gulch lies
just outside the rules box, so it gets the "no camping rules are recorded" Unknown.
Nothing in the pilot is ever Permitted on a guess.

## The data run

`make data REGION=front-range-co` on 2026-11-17, Apple Silicon laptop, into a fresh
database `campsite_tm05_173` (migrated from empty). The Adirondacks and White Mountains
data in other databases were not touched.

| Step | Result | Seconds |
|---|---|---|
| padus | 30 records | 4.8 |
| nhd-flowlines | 903 | 4.3 |
| nhd-waterbodies | 167 | 2.2 |
| osm-trails | 188 | 36.1 |
| osm-campsites | 2 | 45.8 |
| osm-landmarks | 29 | 40.0 |
| ridb | skipped (no API key) | 0 |
| osm-routes | 0 | 30.6 |
| osm-connectors | 67 | 39.1 |
| trail-graph | 440 edges, 380 nodes, 4,848 elevation samples | 34.9 |
| route-profiles | 0 named routes | 1.9 |
| enrich | 1 campsite, every fact 100% | 8.6 |
| access | 0 trailheads on the graph, so access unknown | 1.5 |
| route-facts | 0 routes | 1.2 |
| terrain | 12 tasks, 1 campsite, 575 zone polygons | 285.8 |
| **total** | every step ok except ridb (skipped) | **536.9** (9 min wall, 304 MB peak RSS) |

The full log is `artifacts/terrain/pipeline/front-range-co-run-2026-11-17.txt`.
`pytest -m data` passed (4 of 4) against the pilot database afterwards.

**Coverage.** Enrichment covered 1 of the 2 campsites. Ruby Gulch is outside the box,
so it was ingested (OSM returns ways that cross the edge) but not enriched. There are
no OSM route relations or trailheads in the box, so route and access facts are empty.
Terrain covered the one enriched campsite on every fact except water view (0 of 1).

## What's left

- **More campsites.** OSM maps only 2 sites here. The designated sites in the Indian
  Peaks are listed in the Forest Service zone-map PDFs, and Recreation.gov needs an
  `RIDB_API_KEY`. Either would make the pilot more useful.
- **Regional terrain values.** The pilot runs on the terrain defaults: wind from 270° and
  Eastern Daylight Time. Colorado is on Mountain Daylight Time (UTC−06:00), so the
  "sunrise to 10:00" morning-sun window is read two hours off. Adding
  `regional.summer_utc_offset.front-range-co` to `backend/terrain/tools.yml` is a
  one-line fix, but it changes the registry digest, which recomputes every region's
  terrain tiles. So it was left for a follow-up, to keep the existing regions unchanged
  in this PR.
- **A snapshot.** The pilot data are not in a release dump yet.
- **More rules** from the zone-map PDFs and the Brainard seasonal-regulations page.
