# Scoring

CampSite scores a location from 0 to 100 with a transparent weighted model. This document
has two parts:

1. **The output contract** — the shape every score takes, for anyone *consuming* scores
   (TM05-45's scored-campsites endpoint, TM05-47/48's score display and colouring). It is
   versioned and changes deliberately.
2. **The model** — how the number is produced: factors, curves, weights.

---

## 1. Output contract (version 1, revision 1.1)

Revision 1.1 (TM05-76) added `suitability_score` and `legal_status`. It only adds fields,
so `contract` is still `1` and every contract-1 consumer keeps working (see the change log
at the end of this section).

A score is a JSON object. Every field below is always present; nothing is omitted when
empty, it is `null` or `[]` instead, so a consumer never has to test for a missing key.

```json
{
  "contract": 1,
  "model_version": "1.2.0",
  "config_digest": "a33b94ce",
  "location": { "lon": -73.9512, "lat": 44.1847 },
  "score": 81,
  "factors": [
    {
      "key": "water",
      "label": "Water",
      "status": "scored",
      "score": 96.2,
      "weight": 0.35,
      "effective_weight": 0.4118,
      "contribution": 39.6,
      "measurement": {
        "distance_m": 71.4,
        "ideal_m": 60,
        "feature_type": "stream",
        "perennial": true,
        "name": "Johns Brook",
        "source": "nhd",
        "source_id": "22300012",
        "nearest_any_m": 71.4
      },
      "explanation": "Perennial stream 71 m away (ideal is about 60 m)."
    },
    {
      "key": "land_cover",
      "label": "Land cover",
      "status": "not_available",
      "score": null,
      "weight": 0.05,
      "effective_weight": 0.0,
      "contribution": 0.0,
      "measurement": null,
      "explanation": "Land cover isn't measured yet."
    }
  ],
  "caps": [],
  "suitability_score": 79,
  "legal_status": {
    "status": "permitted",
    "label": "Public land open to camping",
    "reason": "Inside State Wilderness, open to the public, GAP status 1.",
    "basis": {
      "public_access": "open",
      "gap_status": "1",
      "manager": "NYSDEC",
      "designation": "State Wilderness",
      "parcels": 1
    }
  }
}
```

### Top-level fields

| Field | Type | Meaning |
|---|---|---|
| `contract` | int | Version of *this shape*. Bumped only for a breaking change to field names or meanings. Consumers should check it. |
| `model_version` | string | Version of the scoring model (factors and curves). A new value means scores may differ for the same place. |
| `config_digest` | string | Short hash of the weights/curve configuration actually used. Two scores are comparable only if both `model_version` and `config_digest` match. **Use it as part of any cache key.** |
| `location` | `{lon, lat}` | The point that was scored, WGS84 degrees. |
| `score` | int, 0–100 | The overall score, rounded. Already reflects any `caps`. |
| `factors` | array | One entry per factor, **always in the same order** (see §2), including factors that could not be scored. |
| `caps` | array | Rules that overrode the weighted total. Empty in the common case. |
| `suitability_score` | int 0–100, or `null` | *Since 1.1.* How good a place it is to camp, **leaving legality out**: the same weighted mean over every evaluated factor except `legal`, with no caps. `null` only if nothing but legality could be evaluated. |
| `legal_status` | object | *Since 1.1.* Whether you may camp there, reported separately from the score. See [Legal status (the gate)](#legal-status-the-gate). |

### Legal status (the gate)

`legal_status` is `{status, label, reason, basis}`:

| `status` | When | `label` |
|---|---|---|
| `permitted` | The governing PAD-US parcel's public access is **open** | Public land open to camping |
| `not_permitted` | The governing parcel's access is **closed** | Not permitted |
| `unknown` | Anything else: restricted access, access unknown, outside every mapped parcel, or the legal factor could not be evaluated | Legality unknown |

- **Show it whatever the score says.** A `not_permitted` site can have a high
  `suitability_score` (good water, flat ground). That is the point of the gate: display
  "Not permitted" next to it rather than letting a good number imply you may camp there.
- **`unknown` is never `permitted`.** Outside public land is `unknown`, not
  `not_permitted`: it is probably private, but PAD-US is incomplete, so we do not claim it.
  Restricted access is `unknown` too; the `reason` says a permit may be needed.
- **`reason`** is a sentence for the user. **`basis`** holds the legal factor's measurement
  (`public_access`, `gap_status`, `manager`, `designation`, `parcels`), or `null` when the
  factor could not be evaluated.
- Which access values count as permitted or not permitted is config
  (`factors.legal.gate` in `config.yml`), so it can change without a code change.
- **`score` is unchanged.** It still includes the legal factor and the closed-land cap,
  exactly as in 1.0. New consumers should show `suitability_score` and `legal_status`
  side by side. Existing ones keep working on `score`.
### Factor fields

| Field | Type | Meaning |
|---|---|---|
| `key` | string | Stable identifier: `water`, `legal`, `trail`, `weather`, `slope`, `land_cover`. Use this, not `label`, in code. |
| `label` | string | Human-readable name for display. |
| `status` | string | One of `scored`, `no_data`, `not_available` — see below. |
| `score` | float 0–100, or `null` | This factor's sub-score, one decimal. `null` **only** when `status` is `not_available`. |
| `weight` | float | The configured relative weight. |
| `effective_weight` | float 0–1 | This factor's share of the total after renormalising over the factors that count. 0 when `not_available`. All `effective_weight`s sum to 1. |
| `contribution` | float | `score × effective_weight`, one decimal: how many of the overall points this factor supplied. Contributions sum to the uncapped total (±0.1 for rounding). |
| `measurement` | object or `null` | The raw evidence behind the sub-score. Keys depend on the factor (§2). `null` when nothing was measured. |
| `explanation` | string | One sentence a user can read, e.g. "Perennial stream 71 m away (ideal is about 60 m)." |

### The three statuses

- **`scored`** — measured and scored normally.
- **`no_data`** — we looked and found nothing in range (no water within 3 km, no trail
  within 5 km, not inside any public land parcel). This is real information and it
  *counts*: the factor scores low and keeps its weight.
- **`not_available`** — the factor could not be evaluated at all: it is a placeholder not
  built yet (land cover), or its source was unreachable (weather, slope). It is **excluded** from the
  total and the remaining weights are renormalised, so a missing source neither drags the
  score to zero nor silently inflates it. Display it as "not available", never as 0.

### Caps

A cap is a rule strong enough to override the weighted average. Each entry is:

```json
{ "factor": "legal", "max_score": 0, "reason": "Inside land marked closed to the public." }
```

When present, `score` is already `min(weighted total, max_score)`. Show the reason — a site
with good water and a trail that scores 0 needs to say why. Version 1 has one cap: land
marked **closed** to public access caps the score at 0.

### Edge cases consumers must handle

- `score` can be 0 with perfectly good water and trail factors — check `caps`.
- A factor's `score` can be `null` (`not_available`); do not coerce it to 0.
- `measurement` keys are factor-specific and some values inside can be `null` (an unnamed
  stream has `"name": null`; water with unknown flow has `"perennial": null`).
- More factors will be added. Iterate over `factors`; do not index by position, and ignore
  keys you do not recognise.
- **Scores change over time.** The `weather` factor uses a live forecast, so the same
  campsite scores differently tomorrow. Do not cache a score longer than the weather cache
  (1 hour), and show `factors[weather].measurement.date` so a user knows which day it is
  for. If weather is `not_available` (Open-Meteo down) the score is still valid, it simply
  excludes weather.
- Scores from different `model_version` or `config_digest` values are not comparable.

### The legality verdict (TM05-76 follow-up)

`legal_status` answers "is camping allowed on this **land**?" from PAD-US. The campsite
panel shows a **verdict** for the **site** instead: `legality` on
`GET /api/campsites/<id>/detail/` and on each campsite in a route's detail. It sits
**above** the score, and the panel's factor list no longer shows the legal factor.

Code: `backend/scoring/verdict.py`.

| Verdict | Label |
|---|---|
| `permitted` | Permitted · designated site |
| `not_permitted` | Not permitted |
| `unknown` | Unknown: check current rules |

**Rules**, quoted from official NYS DEC pages (fetched 2026-10-07):

- "Except in an emergency, camping is prohibited above an elevation of **4,000 feet** in
  the Adirondacks." Source:
  [State Land Camping Rules](https://dec.ny.gov/things-to-do/camping/state-land-rules)
- "No camping above **3,500 feet** (except at lean-to)." This applies in the High Peaks
  Wilderness. Source:
  [High Peaks Wilderness Complex](https://dec.ny.gov/places/high-peaks-wilderness-complex)
- "Camping is prohibited within **150 feet** of any road, trail, spring, stream, pond or
  other body of water except at areas designated by a 'Camp Here' disk." Source:
  [State Land Camping Rules](https://dec.ny.gov/things-to-do/camping/state-land-rules)

**Designated** means one of:
- a Recreation.gov (RIDB) listing
- a lean-to
- an OSM record described as "designated", or tagged with a DEC operator

The last two are contributors' claims, not DEC's own list.

**How the verdict is decided:**

1. **Land closed** (PAD-US): **Not permitted**. A "designated" site on closed land is
   **Unknown**, because the data disagree.
2. **Elevation limits** apply only inside the Adirondacks: 4,000 ft everywhere there, and
   3,500 ft in the High Peaks Wilderness except at lean-tos. The elevation is the site's
   stored 3DEP value.
   - **Within 50 ft of a limit**, or above one for a designated site: **Unknown**. A
     point elevation is not exact, and the designation evidence is not DEC's list.
   - An undesignated site **more than 50 ft above** a limit: **Not permitted**.
3. **Designated**, and clear of every limit: **Permitted · designated site**. A designated
   Adirondack site with no stored elevation is Unknown, since its limits cannot be checked.
4. **Designation not confirmed**: **Unknown**. At-large camping is legal on open Forest
   Preserve land 150 ft from roads, trails and water, but roads are not in our data, so we
   never call it permitted.

The verdict is never "Permitted" or "Not permitted" on a rule we could not verify from an
official source.

**Sno-bird** (`node/4252860218`, High Peaks Wilderness) is tagged "NYSDEC designated
campsite" and has a stored elevation of **4,028 ft**. That is 28 ft above the Adirondack
limit, within the 50 ft margin. Verdict: **Unknown: check current rules**, with the 4,000 ft
rule cited.

**Trail access wording.** A designated site closer to a trail than the trail factor's
ideal distance adds: "Designated sites are often this close to a trail; that is normal for
a designated site." The 150 ft rule does not apply to designated sites. The sub-score is
unchanged; 354 sites carry the note.

**Measured** (dev DB, 1,500 sites, 2026-10-07):

| Verdict | Sites |
|---|---|
| Permitted · designated site | 968 |
| Unknown: check current rules | 526 |
| Not permitted | 6 (closed land) |

**483 sites changed** from the land-only gate:
- 411 went from permitted to unknown: undesignated OSM sites on open land, which are no
  longer called legal without a designation.
- 70 went from unknown to permitted: mostly RIDB campgrounds outside PAD-US parcels.
- 2 designated sites on closed land went from not permitted to unknown.

No undesignated site lies clearly above an elevation limit today.

Designation evidence: RIDB 660, lean-to 180, OSM "designated" 75, OSM DEC operator 58, none
527.

### Stability promise

Within `contract: 1`, fields are only ever **added**, never renamed, removed or re-typed.
New factor keys may appear. Anything breaking bumps `contract`.

### Change log

| Revision | Story | Change |
|---|---|---|
| 1.0 | TM05-43 | The contract as first published. |
| 1.1 | TM05-76 | Added `suitability_score` and `legal_status`. Additive only, so `contract` stays `1`. A consumer that rejects any `contract` other than `1` (as the campsite panel's `parseScore` does) keeps working. |

---

## 2. The model

Code: `backend/scoring/` — `config.yml` (every tunable number), `curves.py` (the distance
curves), `factors.py` (one class per factor), `engine.py` (`score_location(lon, lat)`,
`score_campsite(campsite)`). Distances come from `geodata.distance` (TM05-42), so they are
metres and index-backed.

### Combining factors

```
total = Σ weight_i × score_i / Σ weight_i      over factors whose status is not not_available
score = round(min(total, every cap))
```

A weighted mean rather than a weighted sum, so weights are *relative*: they need not add
to 1, and a factor that cannot be evaluated drops out without distorting the scale. Factors
appear in the output in the order of `weights` in `config.yml`.

### Weights (model 1.2.0)

| Factor | Weight | Share today | Why |
|---|---|---|---|
| `water` | 0.35 | 32% | The thing a backcountry site most depends on. |
| `legal` | 0.30 | 27% | Whether you may camp there at all. Also the only factor that can cap. |
| `trail` | 0.20 | 18% | Reachability. Matters, but a short bushwhack is fine. |
| `weather` | 0.15 | 14% | Tonight's conditions. Real, but it changes daily and does not make a place better or worse. |
| `slope` | 0.10 | 9% | Whether there is flat ground to sleep on (TM05-64). |
| `land_cover` | 0.05 | — | Placeholder; counts once Sentinel-2 lands. |

"Share today" is the effective weight while land cover is `not_available` (0.35 / 1.10
and so on). Model 1.0.0 (TM05-43) had no weather; 1.1.0 (TM05-44) added it; 1.2.0
(TM05-64) replaced the slope placeholder with a real factor. Change a weight by editing
`config.yml`; no code changes, and the
`config_digest` on every score changes with it.

### The distance curves

Closest is not best. Leave No Trace asks for camps about **200 ft (≈60 m) from water** and
away from trails, so both curves peak at an ideal distance and fall off on both sides:

```
d ≤ ideal :  score = at_zero + (100 − at_zero) × d / ideal          (linear rise)
d > ideal :  score = 100 × 0.5 ^ ((d − ideal) / half_distance)     (halves every half_distance)
```

| Distance | Water (ideal 60, bank 35, half 400 m) | Trail (ideal 60, on-trail 50, half 800 m) |
|---|---|---|
| 0 m | 35 | 50 |
| 30 m | 68 | 75 |
| 60 m | **100** | **100** |
| 200 m | 78 | 89 |
| 460 m | 50 | 71 |
| 1 km | 20 | 44 |
| 3 km | 0.6 | 8 |
| beyond search | 0 (`no_data`, > 3 km) | 0 (`no_data`, > 5 km) |

The trail curve is gentler on both sides: sitting on a trail is less of a problem than
sitting on a stream bank, and walking a kilometre to a trail is ordinary.

### Water

The nearest water is not always the water that matters — a wetland 40 m away should not
hide a perennial stream at 120 m. So the factor takes the **5 nearest features of each flow
class** (perennial / unknown / intermittent), scores each with

```
curve(distance) × flow_multiplier × feature_multiplier
```

and keeps the best. Flow multipliers: perennial **1.0**, unknown **0.8**, intermittent
**0.55** — intermittent water may be dry when you arrive. Feature multipliers: stream, lake,
spring 1.0; wetland 0.5; other 0.7. When the winning feature is not the closest one,
the explanation says so ("Nearer water (intermittent stream, 33 m) scored lower.") and
`measurement.nearest_any_m` gives the closest distance.

`measurement`: `distance_m`, `ideal_m`, `feature_type`, `perennial` (true / false / null),
`name` (null if unnamed), `source`, `source_id`, `nearest_any_m`. With nothing in 3 km:
`status: no_data`, score 0, `distance_m: null`, plus `max_search_m`.

### Legal status

From PAD-US: the parcels whose polygon contains the point.

- **Access** (`public_access`): open **100**, restricted **45**, unknown **40**, closed **0**.
  Where parcels overlap, the **most restrictive** access applies — this is a legal question,
  so the stricter rule is assumed.
- **GAP status** multiplies it: 1 and 2 (managed for a natural state) ×1.0, 3 ×0.9,
  4 (no protection mandate) ×0.75, unknown ×0.85. Taken from the best-protected parcel among
  those that set the access.
- **Closed land caps the overall score at 0**, whatever water and trail say, with a `caps`
  entry giving the reason.
- **Outside every parcel**: `status: no_data`, score **15** — probably private land, but
  PAD-US is incomplete, so not zero.
- **The gate (TM05-76).** The same facts also decide `legal_status`, which is reported
  beside the score (§1). The factor's weight still shapes `score`; the gate is what says
  whether camping is allowed.

`measurement`: `public_access`, `gap_status`, `manager`, `designation` (all null outside
public land), `parcels` (how many contain the point).

### Trail access

Nearest trail segment (OSM ways, TM05-26 filtering), scored on the trail curve.
`measurement`: `distance_m`, `ideal_m`, `name`, `trail_type`, `source`, `source_id`. Nothing
within 5 km: `no_data`, score 0.

### Weather

From the live Open-Meteo forecast, through the analysis cache (TM05-44, see
docs/architecture.md): snapped to a 0.05° grid, cached one hour. Scored on forecast day 0 —
today, i.e. tonight's camp:

```
score = 100 − min(40, 4 × rain_mm) − min(30, max(0, wind_max_kmh − 25)) − min(30, 3 × max(0, −low_c))
```

Each penalty is capped so one bad element cannot zero the factor alone: 5 mm of rain costs
20 points, a 40 km/h day 15, a −5 °C night 15. If Open-Meteo cannot be reached, the factor is
`not_available` and drops out of the total.

`measurement`: `date`, `precipitation_mm`, `precipitation_probability_pct`, `wind_max_kmh`,
`temperature_min_c`, `temperature_max_c`, `penalties` (`precipitation`, `wind`,
`freezing`), `grid` (the cell the forecast is for), `fetched_at`, `cached`.

### Slope (TM05-64)

Ground slope at the site from USGS 3DEP, through the `site_terrain` analysis — the same
cache `enrich_campsites` fills, so an enriched campsite never waits on 3DEP here. Slope is
Horn's method over a 3x3 stencil of elevations 10 m apart (20 m across: a tent pad and the
ground around it); see docs/enrichment.md. Flatter is better, interpolated linearly
through the `curve` points in `config.yml`:

| Slope | 0–3° | 5.5° | 8° | 11.5° | 15° | ≥ 20° |
|---|---|---|---|---|---|---|
| Sub-score | **100** | 75 | 50 | 30 | 10 | 0 |

3° is any tent pad; around 8° a sleeping pad starts to slide; 15° is a hillside nobody
sleeps on. If 3DEP is unreachable the factor is `not_available` and drops out, like weather.

`measurement`: `slope_deg`, `slope_pct`, `elevation_m`, `stencil_m`, `cached`.
Explanation, e.g. "Ground is gently sloping: 6° (10%) across 20 m."

**Caveat:** 3DEP is hydro-flattened. A site whose mapped point falls on a pond or lake
(Marcy Dam's does) reads exactly 0° — water, not ground.

### Placeholder: land cover

`LandCoverFactor` is a real factor class with a weight in the config, returning
`not_available` with an explanation. A later story replaces its `evaluate()` with a real
measurement; the engine, the config shape and the output contract stay as they are.

### What is deliberately *not* a factor

**Capacity.** 571 of the 660 RIDB campsites report the same capacity, 8 — a default, not a
measurement — so it would add noise that looks like signal. `score_campsite()` scores a
campsite by its location only; a test asserts two sites at the same point with capacities 2
and 40 score identically.

### Performance (measured)

`python manage.py bench_scoring`, 2026-10-02, local Docker PostGIS (emulated on Apple
Silicon, so pessimistic):

| Run | Time |
|---|---|
| 100 campsites, model 1.0.0 (median of 3 warm runs) | **934 ms** — 9.3 ms per site |
| All 1,320 campsites, model 1.0.0 (one run) | 18.1 s — 13.7 ms per site |
| 100 campsites, model 1.1.0 with weather, cold weather cache | 6.7 s — 5 Open-Meteo calls (5 grid cells) |
| 100 campsites, model 1.1.0, warm (median of 3) | **1,180 ms** — 11.8 ms per site |

Per factor, 100 sites: water 675 ms (three KNN queries of 5), trail 190 ms, legal 142 ms,
placeholders ~2 ms. Water is the obvious target if this ever matters: one query ordered by
flow class would replace three.

Score distribution over all 1,320 campsites (model 1.0.0): min 0, median 56, max 98.

### PAD-US coverage (fixed in TM05-57)

Model 1.0.0 shipped with only **199 of 1,320** campsites inside any PAD-US parcel, so most
sites scored the 15-point "not public" legal value — including Marcy Dam in the High Peaks
Wilderness. The cause was ingestion: invalid parcels were skipped. TM05-57 repairs them
with `ST_MakeValid` (docs/pipeline.md), and **1,174 of 1,320** campsites now fall inside a
parcel. Measured over all 1,320 campsites, same model (1.1.0) and weights:

| | Median | Mean | Stdev | Min / max |
|---|---|---|---|---|
| Before TM05-57, weather excluded | 56 | 56.3 | 12.55 | 0 / 98 |
| After TM05-57, weather excluded | 79 | 76.7 | 13.19 | 0 / 99 |
| Before TM05-57, with live weather | 61 | 61.7 | 11.06 | 0 / 98 |
| After TM05-57, with live weather | 81 | 79.0 | 11.57 | 0 / 98 |

The weather-excluded rows are the fair comparison; the forecast changes hourly.

### Stored values only (TM05-45)

`score_location(..., stored_only=True)` and `score_campsite(..., stored_only=True)` score
without any live call. Factors read from analyses (slope, weather) use
`Analysis.lookup()`, which returns a fresh cached answer or nothing and never computes;
on a miss the factor is `not_available`. The campsite detail endpoint scores this way.

### Adding a factor

1. Write a `Factor` subclass in `factors.py` (or its own module) with `key`, `label` and
   `evaluate(lon, lat) -> FactorResult`, and decorate it with `@register`.
2. Add its weight under `weights:` and its settings under `factors:` in `config.yml`.
3. Document its curve and `measurement` keys here.

Nothing in `engine.py` changes. TM05-44 added weather exactly this way.
