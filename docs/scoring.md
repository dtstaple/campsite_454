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
  "model_version": "1.0.0",
  "config_digest": "3f9a1c2e",
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
        "source_id": "nhd:22300012"
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
| `key` | string | Stable identifier: `water`, `legal`, `trail`, `slope`, `land_cover`, and from TM05-44 `weather`. Use this, not `label`, in code. |
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
- More factors will be added (weather in TM05-44). Iterate over `factors`; do not index by
  position, and ignore keys you do not recognise.
- Scores from different `model_version` or `config_digest` values are not comparable.

### Stability promise

Within `contract: 1`, fields are only ever **added**, never renamed, removed or re-typed.
New factor keys may appear. Anything breaking bumps `contract`.

---

## 2. The model

*Filled in with the implementation below.*
