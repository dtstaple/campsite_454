# Scoring

CampSite scores a location from 0 to 100 with a transparent weighted model. This document
has two parts:

1. **The output contract** — the shape every score takes, for anyone *consuming* scores
   (TM05-45's scored-campsites endpoint, TM05-47/48's score display and colouring). It is
   versioned and changes deliberately.
2. **The model** — how the number is produced: factors, curves, weights.

---

## 1. Output contract (version 1)

A score is a JSON object. Every field below is always present; nothing is omitted when
empty, it is `null` or `[]` instead, so a consumer never has to test for a missing key.

```json
{
  "contract": 1,
  "model_version": "1.1.0",
  "config_digest": "0a9724fd",
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
      "key": "slope",
      "label": "Slope",
      "status": "not_available",
      "score": null,
      "weight": 0.1,
      "effective_weight": 0.0,
      "contribution": 0.0,
      "measurement": null,
      "explanation": "Slope is not measured yet (planned: USGS 3DEP)."
    }
  ],
  "caps": []
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
  built yet (slope, land cover), or its source was unreachable. It is **excluded** from the
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

### Stability promise

Within `contract: 1`, fields are only ever **added**, never renamed, removed or re-typed.
New factor keys may appear. Anything breaking bumps `contract`.

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

### Weights (model 1.1.0)

| Factor | Weight | Share today | Why |
|---|---|---|---|
| `water` | 0.35 | 35% | The thing a backcountry site most depends on. |
| `legal` | 0.30 | 30% | Whether you may camp there at all. Also the only factor that can cap. |
| `trail` | 0.20 | 20% | Reachability. Matters, but a short bushwhack is fine. |
| `weather` | 0.15 | 15% | Tonight's conditions. Real, but it changes daily and does not make a place better or worse. |
| `slope` | 0.10 | — | Placeholder; counts once 3DEP lands. |
| `land_cover` | 0.05 | — | Placeholder; counts once Sentinel-2 lands. |

"Share today" is the effective weight while slope and land cover are `not_available`
(0.35 / 1.00 and so on). Model 1.0.0 (TM05-43) had no weather; 1.1.0 (TM05-44) added
it. Change a weight by editing `config.yml`; no code changes, and the
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

### Placeholders: slope and land cover

Both are real factor classes (`SlopeFactor`, `LandCoverFactor`) with weights in the config,
returning `not_available` with an explanation. Sprint 5 replaces each class's `evaluate()`
with a real measurement; the engine, the config shape and the output contract stay as they
are.

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

### Known limitation: PAD-US coverage

Only **199 of 1,320** ingested campsites fall inside any PAD-US parcel, so most sites score
the 15-point "not public" legal value — including places that are plainly public land, such
as Marcy Dam in the High Peaks Wilderness. The cause is in ingestion, not scoring: the last
PAD-US runs are `partial` and skipped 49 parcels as invalid geometry ("Ring
Self-intersection", "Nested shells"), and the large wilderness and forest units are among
them. They need repairing with `ST_MakeValid` rather than skipping; that is tracked as its
own story. Until then, the legal factor is right about the parcels it has and pessimistic
about the rest.

### Adding a factor

1. Write a `Factor` subclass in `factors.py` (or its own module) with `key`, `label` and
   `evaluate(lon, lat) -> FactorResult`, and decorate it with `@register`.
2. Add its weight under `weights:` and its settings under `factors:` in `config.yml`.
3. Document its curve and `measurement` keys here.

Nothing in `engine.py` changes. TM05-44 added weather exactly this way.
