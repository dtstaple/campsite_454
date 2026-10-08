# Run report: Sprint 5, batch 1 (2026-10-07)

Six stories, in order: TM05-76, TM05-75, TM05-77, TM05-82, TM05-73, TM05-71.

**Process, for every story:**
- one branch from an up-to-date `main`
- the gate before every commit: ruff check, ruff format, pytest, then frontend lint and build (plus `npm test`)
- PR, CI green, merge commit, then pull `main`

No branch was stacked on another, and no PR needed a CI fix.

**Setup and finish:**
- `make doctor` passed at the start and at the end.
- End state: 1,500 campsites, 743 enriched, 452 routes.

**Jira:**
- All six stories are still **In Progress**.
- No worklogs.
- One PR-link comment on each story after its merge.

| Story | PR | Merge | Commits |
|---|---|---|---|
| TM05-76 Legality as a separate gate | [#56](https://github.com/dtstaple/campsite_454/pull/56) | merged `20e3ccb` | 3 |
| TM05-75 Adirondack lean-tos | [#57](https://github.com/dtstaple/campsite_454/pull/57) | merged `1c303ba` | 2 |
| TM05-77 Confidence and provenance | [#58](https://github.com/dtstaple/campsite_454/pull/58) | merged `6d14678` | 3 |
| TM05-82 Difficulty and route type | [#59](https://github.com/dtstaple/campsite_454/pull/59) | merged `8d37f00` | 3 |
| TM05-73 Mile-0 snapping | [#60](https://github.com/dtstaple/campsite_454/pull/60) | merged `f0dd110` | 3 |
| TM05-71 Derived names in the trail list | [#61](https://github.com/dtstaple/campsite_454/pull/61) | merged `ce4d542` | 2 |

---

## TM05-76: Treat camping legality as a separate gate in scoring

Every score now carries **`legal_status`** (`permitted` / `not_permitted` / `unknown`, with
`label`, `reason`, `basis`) and **`suitability_score`** (the weighted mean without
legality) beside the unchanged `score`.

- Code: `backend/scoring/legal_gate.py` and `engine.py`.
- Gate config: `factors.legal.gate` in `config.yml`.

| AC | Status |
|---|---|
| The scoring output reports legal status separately from the suitability score | **Met.** `legal_status` and `suitability_score` are new top-level fields. |
| A site that isn't legally eligible is flagged as such no matter its score | **Met.** Closed land is `not_permitted`. A test has suitability ≥ 80 with `not_permitted`. |
| Unknown legality is shown as unknown, never as permitted | **Met.** Restricted, unknown, no parcel and not-available are all `unknown`. |
| docs/scoring.md is updated | **Met.** Contract §1, the gate table, a change log, and the model's legal section. |
| Tests cover permitted, not permitted, and unknown | **Met.** 9 new tests in `tests/test_scoring.py::TestLegalGate`. |

**Measured** over all 1,320 campsites (stored values only, 27 s):
- **1,150 permitted, 164 unknown, 6 not permitted.**
- Of the unknown:
  - 95 OSM and 51 RIDB sites are outside every PAD-US parcel
  - 13 are on restricted-access land (8 Wilderness Area, 4 easement, 1 conservation area)
  - 3 are on land with unknown access
- 84 non-permitted sites have suitability ≥ 80. This is the case the gate exists for.

**Judgment calls:**
- **`contract` stays `1`; the docs call this revision 1.1.**
  - The brief said "bump the contract version", but docs/scoring.md's own stability promise says additive changes stay within contract 1.
  - TM05-47's `parseScore` rejects `contract !== 1` by design, and its test treats `contract: 2` as "a future, breaking contract". Bumping the integer would have blanked the panel's breakdown.
  - So: no consumer change, and the doc version and change log record the revision.
- **Outside public land → `unknown`, not `not_permitted`.** It is probably private, but PAD-US is incomplete.
- **Restricted access → `unknown`**, with "may need a permit" in the reason.
- **`score` keeps the legal factor and the closed-land cap** for backward compatibility. `suitability_score` is the clean one.
- **Follow-up candidate, not done:** the 51 RIDB sites outside any parcel are official reservable campgrounds, which are clearly legal. A record-level rule ("an official RIDB listing is permitted") would fix them. Left out: scoring is location-based, and adding it would change the gate's meaning.

**Protected-file edit:** `tests/test_api_campsite_score.py` (TM05-45, Abdulrahman). His key-set assertion pins the exact fields of the score, so I added `suitability_score` and `legal_status` to the expected set. 2 lines; nothing else changed.

### Draft comments, not posted

**For TM05-86 (Abdulrahman):**
> TM05-76 (merged, #56) adds two fields to every score: `suitability_score` (0–100 or null, the weighted mean without legality) and `legal_status` (`{status: permitted|not_permitted|unknown, label, reason, basis}`). `contract` is still 1 (revision 1.1, additive), and `score` is unchanged. For the map layer, please carry `legal_status.status` as a feature property next to `score`/`score_status`, so Sahaj can mark not-permitted sites whatever their colour. It's the same stored-values-only computation, so there's no extra cost. docs/scoring.md §1 has the details. Note: I added the two new keys to your key-set assertion in `tests/test_api_campsite_score.py`, nothing else.

**For TM05-72 (Sahaj):**
> TM05-76 (merged, #56): every score now has `legal_status` (`permitted` / `not_permitted` / `unknown`, with a user-facing `label` and `reason`) and `suitability_score` (the score without legality). `contract` is still 1, so `parseScore` keeps working unchanged. Suggestion for the markers and the panel: a not-permitted site should show that state whatever its grade colour (for example a crossed marker, plus "Not permitted" and the reason in the panel), and unknown should never look permitted. 6 sites are not_permitted today and 164 are unknown. docs/scoring.md "Legal status (the gate)" has the rules.

---

## TM05-75: Ingest Adirondack lean-tos as campsites

The OSM campsites adapter also asks for `amenity=shelter` + `shelter_type=lean_to` (nodes and
ways) in the same Overpass union. These become `site_type lean_to`.

| AC | Status |
|---|---|
| The OSM campsites adapter also ingests lean-to shelters, with site_type lean_to | **Met** |
| Duplicates are avoided where a lean-to is also tagged as a campsite | **Met.** One row per OSM element (Overpass union, plus a `source_id` guard in normalize). |
| The new sites are enriched and scored like the existing ones | **Met.** All 743 enriched; lean-to scores n 180, median 80, range 0–99. |
| The before/after count of sites along at least two named High Peaks trails is measured and recorded | **Met.** Three routes; table below and in docs/pipeline.md. |

**Measured (dev DB):**
- **Ingest:** `ingest osm-campsites adirondacks` gave **743** records (563 before), all 180 new ones lean-tos. It succeeded after 1 Overpass retry, in 22 s.
- **Enrichment:** `enrich_campsites adirondacks` covered 743 sites in **137.1 s**, of which terrain took 120.7 s through 3DEP 502/504 retries.
  - elevation and slope 100%, public land 89.8%, named trail 98.9%
  - derived names for 382 of 383 unnamed sites
- **Coherence:** `pytest -m data` passes 4/4 on the new data.

| Route (sites within 500 m) | Before | After | Of which lean-tos |
|---|---|---|---|
| Northville-Placid Trail | 28 | 61 | 33 |
| Phelps Trail | 14 | 22 | 8 |
| Van Hoevenberg Trail | 4 | 8 | 4 |

**Within 15 m: reported, not merged** (per the brief):
- **1 lean-to beside a separately mapped campsite:** Panther Gorge Leanto `node/2727109610` and unnamed `node/5042026592`, **12.4 m** apart.
- **9 lean-to pairs within 15 m of each other.** Numbered pairs are common in the Adirondacks.

**Judgment calls:**
- **Run parameters:** I kept `tourism_value` alongside the new `tag_filters`, so existing readers and tests are unaffected.
- **Other shelters are not ingested:** picnic shelters and basic huts aren't campsites.

**Note:** the published dev-data snapshot (`dev-data-2026-10-05`) predates this run and has no lean-tos. TM05-90 (Bleron) will publish a refreshed one.

---

## TM05-77: Campsite confidence and data provenance

**Levels** (`backend/geodata/confidence.py`; rules in `docs/confidence.md`):
- **official:** RIDB only.
- **community_mapped:** OSM with a name or with at least 2 informative tags. This includes records tagged `operator=NYSDEC` (136 do); the operator is shown separately.
- **limited_info:** OSM with no name and fewer than 2 informative tags.

| AC | Status |
|---|---|
| Each campsite has a confidence level derived from its source and data completeness | **Met** |
| The detail panel shows the confidence level, the data source, and when the data was last updated | **Met.** New **Data** row: the level, then "Recreation.gov (RIDB) · updated Sep 19, 2026". The date is `IngestRun.finished_at` through `last_run`. |
| The levels and their rules are documented | **Met.** `docs/confidence.md`, plus the field in docs/api.md. |
| Tests cover each level | **Met.** 11 backend tests (each level, the edge cases, the NYSDEC operator, IngestRun date, endpoint) and 2 frontend tests. |

**Measured (1,500 records):** 660 official, 569 community-mapped, 271 limited info.

**Judgment calls:**
- **"Informative tags"** = enrichment's surfaced OSM tags plus the tags the adapter reads (shelter_type, backcountry and so on). `tourism`, `amenity` and blank values don't count. The threshold is 2.
- **"Last updated" means when we last ingested the record,** not the OSM edit date. The query doesn't fetch element metadata; the docs say so.
- **Unknown future sources** default to `limited_info`.

---

## TM05-82: Trail difficulty and route type

| AC | Status |
|---|---|
| Difficulty (Easy, Moderate, Hard) is computed from distance and elevation gain, using documented thresholds kept in config | **Met.** Shenandoah `sqrt(climb_ft × 2 × distance_mi)`; bands Easy below 50, Moderate 50 to below 150, Hard 150+ in `backend/geodata/routes.yml`. |
| Route type is computed from the geometry: start and end within a set distance means a loop, otherwise point-to-point, and documented heuristics identify out-and-back | **Met.** Loop within 200 m (measured). Ends are classified summit, connects, pond or dead_end, and the result is labelled estimated. docs/routes.md. |
| Both appear in the trail panel and in the route API | **Met.** Route detail: `difficulty`, `route_type`. Panel: "Difficulty" and "Type", with "(est.)" and a tooltip. |
| Tests cover each difficulty band and each route type | **Met.** 5 band cases plus boundaries and config; loop, summit, flat, pond, dead end, point to point and own-ways cases; API and frontend wording. |

**Measured:**
- **All 452 routes** (14 s): **260 point to point, 173 out & back, 19 loops.**
- **Most common end pairs:** both connect (225); connects + dead end (134); both dead end (35).
- **Difficulty for the 21 routes with a cached profile:** 14 Moderate, 5 Hard, 2 Easy.
  - Van Hoevenberg: Hard (216), out & back to a summit
  - Mount Marcy Trail: Moderate (147)
  - Cranberry Lake 50: a loop, Hard (568)

**Judgment calls:**
- **"Gain" is `max(gain, loss)`,** the climb in the harder direction. Franconia Brook Trail is mapped downhill (gain 0): it rated Easy, 0 before this change and Hard, 167 after.
- **Shenandoah's five bands are folded into three.** "Moderately strenuous" (100–150) counts as Moderate.
- **A summit needs at least 100 m of relief along the route.** Without that, a flat route's ends read as summits (Southside Trail).
- **End check order: summit → connects → pond → dead_end.**
  - A summit stays a destination even where trails meet, as at Marcy.
  - A junction at a lake stays a junction. The first pass checked ponds first, which made Avalanche Pass out & back; the order was revised.
- **Known limitation, documented:** roads are not mapped, so a road trailhead reads as a dead end.
  - The Northville-Placid Trail comes out as "Out & back (est.)".
  - Kept as you specified, because the rule "a dead end means out & back" was given in the brief.
  - TM05-89's trailheads would fix it.
- **Scope:** the fields are on the route **detail** only, which is what the panel reads, not the route list. Route type needs per-route end queries, so the list doesn't carry them. TM05-85 (filters) can add list support.

---

## TM05-73: Stop sites past a trail's end from snapping to mile 0

| AC | Status |
|---|---|
| Sites whose nearest point is a trail endpoint and that are farther than a set distance are labelled "near the trailhead" or "near the trail's end" instead of a mile marker | **Met.** `position` / `position_label` on each listed site. The trail list shows "—" and "near the trailhead · 763 m away". |
| The distance threshold lives in config | **Met.** `along.off_end_m: 100`, `along.end_zone_m: 50` in `routes.yml`. |
| Tests cover a mid-trail site, a site past either end, and a site beyond the threshold | **Met.** 7 rule tests, an API test with four placed sites, and 3 frontend tests. |

**Measured (all 452 routes at 500 m, 869 listed sites):**
- **574 along, 140 near the trailhead, 155 near the trail's end**, on 67 routes.
- **Preston Ponds at 1 km:** the 763 m site and Henderson Lean-to (226 m) now read "near the trailhead". The Duck Hole lean-tos keep mi 4.3 and 4.4.

**Judgment calls:**
- **A 50 m end zone.** The story says "nearest point is a trail endpoint". Real first and last segments curve, so the 763 m site's nearest point is 18 m along (fraction 0.0024), and an exact-vertex check missed the very example in the story.
- **A 100 m threshold** is the conservative choice: a site under 100 m from the start keeps "mi 0.0".
- **"Trailhead" means the start of the stitched line,** which isn't always the end hikers use. Documented.
- **No profile marker or cursor** for sites past an end, since there's no place on the profile to show.

---

## TM05-71: Show derived campsite names in the trail list

| AC | Status |
|---|---|
| The trail list uses the same display name as the detail panel, styled as derived where applicable | **Met.** The route API returns `display_name` / `display_name_derived`, built exactly as the detail endpoint builds them. Derived names are italic, in the secondary text colour, with the panel's tooltip. |
| Sites with a real name are unaffected | **Met.** Tested. |
| A test covers a named site and a derived-name site | **Met.** 4 backend tests (including list and detail agreeing, and unenriched sites) and 3 frontend tests. |

**Measured:**
- **East River Trail:** the unnamed sites now read "Campsite near Calamity Brook Trail" and "Campsite near Calamity Brook".
- **Van Hoevenberg:** "Campsite near Van Hoevenberg Trail" twice.
- **Database-wide:** 382 of 402 unnamed sites have a derived name. The other 20 are unenriched and fall back to "Unnamed campsite".

**Judgment calls:**
- **Field name `display_name_derived`**, not `is_derived`, to match the detail endpoint.
- **The raised pin (TM05-69)** now receives the display name from a list click.

---

## Protected areas

| Area | Touched? |
|---|---|
| Abdulrahman: `backend/accounts/`, saved-campsites, TM05-86 map-layer scoring | **No.** One test edit in his TM05-45 file `tests/test_api_campsite_score.py`: +2 expected keys (see TM05-76). `backend/api/campsite_detail.py` gained the additive `confidence` key and a `select_related` (TM05-77); the scoring path is unchanged. |
| Sahaj: marker colour paint in `map/layers.ts`, score breakdown UI | **No.** `layers.ts` is untouched. `score/breakdown.ts` and `ScoreBreakdown.tsx` are untouched. `CampsitePanel.tsx` gained a separate Data row in the facts list, outside the breakdown slot. |
| Bleron: peaks/trailheads adapter (TM05-89), Makefile refresh targets (TM05-91) | **No.** Neither exists yet; nothing touched. |

**Other:**
- **Docker:** no containers were created this run, and there was no prune of any kind.
- **Data:** the dev DB was changed only as the brief asked (TM05-75's re-ingest and enrichment).

---

## What to check in the browser

Open http://localhost:5173/discover after `make dev`.

1. **Lean-tos (TM05-75).** In Camping mode, look around the High Peaks.
   - There should be visibly more campsite markers along the Northville-Placid, Phelps and Van Hoevenberg trails.
   - Open a lean-to: the panel should show its name, and site type should read lean-to.
2. **Trail panel, Van Hoevenberg Trail (TM05-82, TM05-71).**
   - **Difficulty:** Hard.
   - **Type:** "Out & back (est.)". Hover it: the tooltip should say one end meets a dead end and the other a summit.
   - **Layout:** check the stats grid with 8 entries.
   - **List:** two unnamed sites should read "Campsite near Van Hoevenberg Trail", in italics.
3. **Preston Ponds Trail (TM05-73).** Set "within" to 1 km.
   - The first two rows should show "—" with "near the trailhead · 763 m away" and "… 226 m away".
   - The profile should have no marker at mile 0 for them, and hovering them should move no cursor.
4. **East River Trail (TM05-71).** The derived names should appear in italics. Clicking one, the raised pin should show the same name.
5. **Campsite panel, Data row (TM05-77).**
   - A White Mountains RIDB site: "Official listing" (green), "Recreation.gov (RIDB) · updated Sep 19, 2026".
   - Marcy Dam: "Community-mapped"; the Operator row still shows NYSDEC.
   - An unnamed OSM site with no tags: "Limited info".
6. **Legality (TM05-76)** has no UI yet. Check the API: `/api/campsites/<id>/detail/` should have `score_breakdown.legal_status` and `suitability_score`, and the score breakdown panel (TM05-47) should still render.
7. **Narrow window (≤ 720 px):** the trail panel becomes a bottom sheet. Check that the "near the trailhead" line and the new stats wrap cleanly.
