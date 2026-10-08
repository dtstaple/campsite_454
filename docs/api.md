# Map data API

Written for the frontend. Everything here returns GeoJSON you can hand straight to
MapLibre as a source — no reshaping needed.

The server runs at `http://localhost:8000` by default (`python manage.py runserver` from
`backend/`). All endpoints are GET, need no authentication, and CORS is already open to
the Vite dev server on port 5173.

---

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/campsites/` | Campsites — points |
| `GET /api/trails/` | Trails — MultiLineStrings |
| `GET /api/water/` | Streams, rivers, lakes, ponds, wetlands — LineStrings and Polygons |
| `GET /api/public-land/` | Public land parcels and legal access — MultiPolygons |
| `GET /api/map-data/` | All four at once, for the initial load |
| `GET /api/campsites/<id>/detail/` | One campsite with its derived facts — see [Campsite detail](#campsite-detail-tm05-64) |
| `GET /api/routes/` | Named hiking routes in a bbox — see [Named routes](#named-routes-tm05-60) |
| `GET /api/routes/<osm_id>/` | One route: stats, elevation profile, campsites along it with scores |

There is one endpoint per layer so you can fetch only what the user has toggled on, and a
combined one so the first paint is a single round trip. They share the same code, so the
shapes never drift apart.

Note `/api/water/` mixes geometry types in one collection — NHD publishes streams as lines
and lakes as polygons, and both are water. If you need them styled differently, filter on
`properties.feature_type` in the layer style rather than expecting separate endpoints.

---

## Parameters

### `bbox` (required)

```
bbox=west,south,east,north
```

Decimal degrees, EPSG:4326. This is exactly what
`map.getBounds().toArray().flat()` gives you, so no reordering is needed:

```js
const [west, south, east, north] = map.getBounds().toArray().flat();
const url = `/api/water/?bbox=${west},${south},${east},${north}`;
```

### `limit` (optional, max 6000)

The most features to return per layer. **Leave it off.** With no `limit`, the cap is
derived from the bounding box area, which is almost always what you want:

| Bounding box area | Default cap | Roughly |
|---|---|---|
| ≤ 0.01 sq° | 6000 | one valley |
| ≤ 0.1 sq° | 4000 | a cluster of valleys |
| ≤ 1.0 sq° | 2500 | a large sub-region |
| ≤ 5.0 sq° | 1500 | the whole Adirondack Park (3.99) |
| above | 1000 | multi-region |

The relationship is inverse on purpose. Zoomed in, the full set is usually smaller than
the cap so nothing is lost. Zoomed out, a smaller well-spread sample both reads better
and transfers faster than a larger one.

### `layers` (optional, `/api/map-data/` only)

Comma-separated subset of `campsites,trails,water`. Defaults to all three.

Use it to skip layers you will not draw. Below zoom 9 an individual stream is well under
a pixel, and asking for `layers=campsites` over the whole park is **223 bytes in 70 ms**
against 138 kB in 416 ms for all three. An unknown name is a 400.

### `simplify` (optional, tolerance in degrees)

Runs the geometry through PostGIS `ST_SimplifyPreserveTopology` before sending it.
**Use this.** At anything wider than a close zoom it is the difference between a 2.6 MB
response and a 211 kB one, and at map scale the shapes look identical.

Roughly: `0.0001` ≈ 11 m, `0.001` ≈ 110 m. Maximum accepted is `0.05`. A reasonable
mapping from zoom:

| Zoom | Suggested `simplify` |
|---|---|
| ≥ 14 (close) | omit it |
| 11–13 | `0.0001` |
| 9–10 | `0.0005` |
| ≤ 8 (regional) | `0.001` |

---

## Try it

With the server running and the Adirondack data ingested:

```bash
curl -s "http://localhost:8000/api/water/?bbox=-74.06,44.10,-74.05,44.11&simplify=0.0005" | jq .
```

Real output, trimmed to two features and three coordinates each:

```json
{
  "type": "FeatureCollection",
  "bbox": [-74.06, 44.1, -74.05, 44.11],
  "features": [
    {
      "type": "Feature",
      "id": "89344051",
      "geometry": {
        "type": "LineString",
        "coordinates": [[-74.05495, 44.11436], [-74.05584, 44.11386], [-74.05763, 44.11478]]
      },
      "properties": {
        "name": "Indian Pass Brook",
        "feature_type": "stream",
        "perennial": true
      }
    },
    {
      "type": "Feature",
      "id": "89344199",
      "geometry": {
        "type": "LineString",
        "coordinates": [[-74.03913, 44.10194], [-74.04189, 44.102], [-74.04395, 44.10115]]
      },
      "properties": {
        "name": "Calamity Brook",
        "feature_type": "stream",
        "perennial": true
      }
    }
  ],
  "metadata": {
    "layer": "water",
    "returned": 3,
    "matched": 3,
    "truncated": false,
    "limit": 2000,
    "simplify": 0.0005
  }
}
```

`bbox` and `metadata` are GeoJSON *foreign members*, which RFC 7946 explicitly allows.
MapLibre ignores what it does not recognise, so you can pass the whole document to
`map.addSource()` unmodified.

### Feature `id`

Every Feature's `id` is the record's **`source_id`** -- the identifier the upstream source
uses, kept verbatim. It is not the database primary key, and the primary key is never sent
to a client.

```
water      "89344051"          NHD permanent identifier
trails     "way/89344051"      OSM way
campsites  "campsite/73996"    RIDB campsite id
```

This is the identifier to hold on to and to send back. `POST /api/saved-campsites/<id>/`
takes exactly this string -- see [auth.md](auth.md). Two consequences worth knowing:

- **It can contain a slash.** Do not assume one path segment when building a URL from it.
- **It survives a re-ingest.** Adapters upsert on `(source, source_id)`, so the same real
  feature keeps the same `id` across runs. A primary key does not survive a rebuild, which
  is why a saved campsite is stored against `source_id` and not against a row number.

`id` is the feature's stable source identifier — the OSM way ID for trails, NHD's
`permanent_identifier` for water, and so on. It is stable across re-ingests.

**MapLibre does not keep it (TM05-63).** MapLibre GeoJSON sources only preserve *numeric*
feature ids. Every id here is a non-numeric string, so a feature returned by
`queryRenderedFeatures` or a click comes back with `id` 0. That is what broke saving
campsites from the map: the popup sent `POST /api/saved-campsites/0/`. The frontend
therefore copies each feature's `id` into `properties.source_id` before `setData()` and
reads it back from there (`frontend/src/map/featureIds.ts`). Read `properties.source_id`
from map features, never `feature.id`. For `setFeatureState()`, use the source's
`promoteId: "source_id"` rather than the raw id.

---

## Properties

Every feature has a `properties` object. `name` is an empty string when the source does
not name the feature — very common for trails, where roughly 40% of OSM ways are unnamed.

**Campsites**

| Property | Type | Notes |
|---|---|---|
| `name` | string | |
| `site_type` | string | `designated`, `primitive`, `lean_to`, `group`, `unknown` |
| `reservable` | bool \| null | `null` means the source does not say — not "no" |
| `capacity` | int \| null | Maximum people, when published |

**Trails**

| Property | Type | Notes |
|---|---|---|
| `name` | string | |
| `trail_type` | string | `path`, `footway`, `track`, `bridleway` |
| `length_m` | float \| null | Metres, geodesic. Accurate to about 0.25% |

**Water**

| Property | Type | Notes |
|---|---|---|
| `name` | string | |
| `feature_type` | string | `stream`, `lake`, `wetland`, `spring`, `other` |
| `perennial` | bool \| null | `true` year-round, `false` intermittent or ephemeral, `null` unknown |

**Public land**

| Property | Type | Notes |
|---|---|---|
| `name` | string | Unit name, e.g. "High Peaks Wilderness" |
| `manager` | string | Managing agency, e.g. "State Department of Conservation" |
| `designation` | string | e.g. "State Wilderness", "Conservation Easement" |
| `public_access` | string | `open`, `restricted`, `closed`, `unknown` — may you enter |
| `gap_status` | string | `1`–`4`, or `""` when unknown — what it is managed *for* |

`public_access` and `gap_status` answer different questions and are easy to conflate.
Access is about entry; GAP status is the conservation mandate, and it is the better
signal for whether dispersed camping is plausible:

| `gap_status` | Meaning |
|---|---|
| `1` | Permanent protection, natural state maintained |
| `2` | Permanent protection, some management permitted |
| `3` | Permanent protection, extractive use allowed |
| `4` | No known protection mandate |

A GAP 4 parcel can be entirely open to the public and still be managed for timber. Do not
read one as the other.

Two behaviours are specific to this layer, both caused by PAD-US publishing some parcels
as a single record aggregating every unit of that name nationally:

- **Membership is tested against the polygon, not its bounding box.** One record's
  bounding box can span the country while none of its polygons are near you. On the
  opening Adirondack viewport a bbox test returns 124 parcels against 87 that genuinely
  intersect.
- **Geometry is clipped to your bbox.** You get the part of each parcel inside the
  viewport, not the whole parcel — 288 KB instead of 982 KB for that same viewport. Pan
  and you get the next part. Do not cache a parcel's geometry as if it were complete.

Three of these are deliberately tri-state. **`null` is not `false`.** For `perennial`,
441 of 63,407 Adirondack water features are genuinely unknown, and rendering those as
"dries up" would be wrong. Check for `null` explicitly before styling on them.

---

## Truncation

The database holds far more than a browser can draw. A bbox over the whole Adirondack Park
matches 63,407 water features, which is **151 MB of raw GeoJSON**. So every response is
capped, and says when the cap bit:

```json
"metadata": { "returned": 2000, "matched": 63407, "truncated": true, "limit": 2000 }
```

- `returned` — features in this response
- `matched` — features that actually intersect the bbox
- `truncated` — `true` when `returned < matched`

When the cap bites, the features you get are a **deterministic spatial sample**, not the
first N rows. The same bounding box always returns the same features, so it is safe to
cache them and a pan back is not a reshuffle. The sample is spread across the whole box
rather than clustered — measured over a 10×10 grid of the park it covers 110 of 140
occupied cells, against 14 for naive truncation.

When `truncated` is `true` the map is showing a subset, so tell the user
rather than letting them think they are seeing everything. Something like *"Showing 2,000
of 63,407 — zoom in to see all"* is enough. `matched` is only computed when the cap bit,
so it costs nothing on normal requests.

On `/api/map-data/` each layer reports its own `metadata`, and the top-level `metadata`
has a `truncated` flag that is `true` if *any* layer truncated.

---

## Errors

A bad request is always a `400` with a readable reason. It is never a 500, and an area
with no features is never a 404.

```json
{ "error": "bbox west (-73.0) must be less than east (-75.0). The order is west,south,east,north." }
```

| Situation | Status | Message contains |
|---|---|---|
| `bbox` missing | 400 | `required`, plus the format |
| Not four values | 400 | `exactly 4 comma-separated values` |
| Non-numeric values | 400 | `must all be numbers` |
| `west >= east` | 400 | `west ... must be less than east` |
| `south >= north` | 400 | `south ... must be less than north` |
| Longitude outside ±180 | 400 | `outside -180..180` |
| Latitude outside ±90 | 400 | `outside -90..90` |
| `limit` not a positive integer | 400 | `whole number` / `at least 1` |
| `simplify` negative or > 0.05 | 400 | `cannot be negative` / `would not resemble` |
| **No features in the area** | **200** | An empty `features` array |

That last row matters: an empty area is a valid answer. You will hit it legitimately —
`/api/campsites/` over the Adirondacks returns zero, because campsite data comes from
Recreation.gov, which is federal-only, and the Adirondacks are New York state land. Use
the White Mountains (`bbox=-72.00,43.85,-70.95,44.55`) to see campsites.

---

## Performance

Measured end to end through the Django test client against the real Adirondack dataset —
1,574 parcels, 26,005 trails, 63,407 water features. Times are the best of three warm runs
on a development laptop, with the PostGIS container running emulated on Apple Silicon, so
treat them as an upper bound rather than production numbers.

| Area | Layer | `simplify` | Time | Size | Returned / matched |
|---|---|---|---|---|---|
| Small, 5.5 km | water | — | 9 ms | 178 kB | 40 / 40 |
| Small, 5.5 km | water | 0.001 | 7 ms | **12 kB** | 40 / 40 |
| Small, 5.5 km | trails | — | 2 ms | 25 kB | 15 / 15 |
| Medium, 33 km | water | — | 99 ms | 2,595 kB | 848 / 848 |
| Medium, 33 km | water | 0.001 | 85 ms | **211 kB** | 848 / 848 |
| Medium, 33 km | trails | — | 17 ms | 386 kB | 481 / 481 |
| Full park | water | — | 594 ms | 5,613 kB | 2,000 / 63,407 ⚠ |
| Full park | water | 0.001 | 342 ms | **447 kB** | 2,000 / 63,407 ⚠ |
| Full park | trails | 0.001 | 69 ms | 437 kB | 2,000 / 26,005 ⚠ |
| Medium, combined | all three | 0.0005 | 217 ms | 359 kB | — |

The headline: **`simplify` is worth more than anything else you can do.** It cuts the
medium-zoom water response by 12× for no visible difference at that scale.

### Index usage

Spatial filtering uses the `&&` operator against the GiST index on every geometry column.
`EXPLAIN (ANALYZE, BUFFERS)` on the medium water query:

```
 Limit  (cost=26.50..3063.25 rows=802 width=61) (actual time=2.639..17.036 rows=848 loops=1)
   Buffers: shared hit=669
   ->  Bitmap Heap Scan on geodata_waterfeature  (cost=26.50..3063.25 rows=802 width=61)
                                                 (actual time=2.543..16.820 rows=848 loops=1)
         Recheck Cond: (geom && '...'::geometry)
         Heap Blocks: exact=548
         ->  Bitmap Index Scan on geodata_waterfeature_geom_27c21cd9_id
                                                 (actual time=1.253..1.256 rows=848 loops=1)
               Index Cond: (geom && '...'::geometry)
               Buffers: shared hit=12
 Execution Time: 18.520 ms
```

**Bitmap Index Scan**, not a sequential scan — the query touches 12 index buffers to find
848 of 63,407 rows. If you ever see `Seq Scan` here, something has gone wrong with the
index.

---

## Campsite detail (TM05-64, scored in TM05-45)

### `GET /api/campsites/<id>/detail/`

`<id>` is the campsite's `source_id`, the same string the map API puts in each Feature's
`id` (and, on the map, in `properties.source_id`). It contains a slash
(`/api/campsites/node/5759412256/detail/`), and the trailing `/detail/` anchors it.
An unknown id returns 404.

The endpoint serves the facts derived by `enrich_campsites` (docs/enrichment.md) and the
campsite's score (TM05-45). The map layers are unaffected.
- **Unknown facts are `null`,** never placeholder text, so the UI can hide them.
- **`facts` is `null`** for a campsite that hasn't been enriched yet; today that's
  everything outside the Adirondacks.
- **The score uses stored values only.** This request never calls 3DEP or Open-Meteo.
  Water, trail and legal status come from the ingested vector tables. Slope and weather
  come from the analysis cache that `enrich_campsites` and other requests fill. An input
  that is not stored is reported as `not_available`; it is not fetched, and it is never
  scored as 0.

```json
{
  "id": "node/5759412256",
  "source": "osm",
  "name": null,
  "display_name": "Campsite near Mud Pond",
  "display_name_derived": true,
  "site_type": "primitive",
  "reservable": null,
  "lon": -74.232066,
  "lat": 43.846018,
  "facts": {
    "public_land": {"name": "Pine Lake Primitive Area", "manager": "State Department of Conservation",
                    "designation": "State Conservation Area", "access": "open", "gap_status": "1"},
    "water": {"name": "Mud Pond", "distance_m": 95.4, "feature_type": "lake", "perennial": true},
    "trail": {"name": "Gooley Club Road", "distance_m": 273.7, "kind": "way"},
    "terrain": {"elevation_m": 495.6, "slope_deg": 5.63, "slope_pct": 9.9},
    "amenities": {"shelter_kind": "tent site", "osm_tags": {"operator": "NY DEC", "tents": "yes"}},
    "method_version": "1",
    "computed_at": "2026-10-02T23:56:32.187176+00:00"
  },
  "score": 84,
  "score_status": "scored",
  "score_breakdown": {
    "contract": 1, "model_version": "1.2.0", "config_digest": "a33b94ce",
    "location": {"lon": -74.232066, "lat": 43.846018},
    "score": 84,
    "factors": [
      {"key": "water", "label": "Water", "status": "scored", "score": 91.2, "weight": 0.35,
       "effective_weight": 0.3684, "contribution": 33.6, "measurement": {"distance_m": 95.4, "...": "..."},
       "explanation": "Lake or pond 95 m away (ideal is about 60 m)."},
      {"key": "weather", "label": "Weather", "status": "not_available", "score": null, "weight": 0.15,
       "effective_weight": 0.0, "contribution": 0.0, "measurement": null,
       "explanation": "No recent forecast stored for here."}
    ],
    "caps": []
  }
}
```

**Score fields (TM05-45):**

| Field | Type | Meaning |
|---|---|---|
| `score` | int 0–100, or `null` | The overall score, the same as `score_breakdown.score`. `null` unless `score_status` is `scored`. |
| `score_status` | string | `scored`: computed from stored values. `pending`: the campsite has not been enriched yet, so there is nothing stored to score it from. `not_available`: enriched, but no weighted factor could be evaluated from stored values. |
| `score_breakdown` | object or `null` | The scoring engine's contract-1 result, with `contract`, `model_version`, `config_digest`, `location`, `score`, `factors` (each with `key`, `label`, `status`, `score`, `weight`, `effective_weight`, `contribution`, `measurement`, `explanation`) and `caps`, plus `suitability_score` and `legal_status` since contract revision 1.1 (TM05-76). docs/scoring.md defines every field. `null` when `score` is `null`. |

| `legality` | object | *TM05-76 follow-up.* The verdict shown above the score: `verdict` (`permitted`, `not_permitted`, `unknown`), `label`, `reason`, `rule` (`{text, source}` quoting the NYS DEC rule, or `null`), `designated`, `designation_basis` and `elevation_ft`. Also on each campsite in a route's detail. docs/scoring.md has the rules. |
| `confidence` | object | *TM05-77.* How far to trust the record: `level` (`official`, `community_mapped`, `limited_info`), `label`, `reason`, `source`, `source_label`, `operator` (the source's operator tag, or `null`), and `last_updated` (ISO 8601: when the ingest that last confirmed the record finished). docs/confidence.md has the rules. |

`score`/`score_breakdown` are the same fields the route detail returns for each campsite.
The difference is that the route detail fetches missing slope and weather live, and this
endpoint does not. The rest of the response is returned whatever the `score_status`; a
score that cannot be computed never makes the request fail. A nonexistent id is a 404.

- **Unenriched sites are not scored.** Most of them lie outside the ingested regions,
  with no water, trail or PAD-US data nearby. Scoring them would report that missing
  data as `no_data`, which means "measured, found nothing", and the result would be a
  misleadingly low score.
- **Weather is often `not_available` here.** The forecast cache lasts one hour (docs/scoring.md), so
  weather is scored only when a recent request (for example a route detail) has already
  fetched the forecast for that grid cell. When it is `not_available`, the weights are
  renormalised and the score is still valid.
- **Slope** is read from the `site_terrain` cache that `enrich_campsites` fills (kept a
  year), so an enriched site normally has it.

**Field notes:**
- **`name`** is the source's own name; `null` when the source had none.
- **`display_name`** is what to show. When `display_name_derived` is `true`, style it as
  derived (e.g. italic) and don't present it as the site's real name.
- **`public_land`, `water`, `trail`, `terrain`** are each `null` when unknown: outside every
  parcel, nothing named within 5 km, or 3DEP unavailable.
- **`trail.kind`** is `route` for a named hiking route (TM05-58) or `way` for a named OSM
  trail segment.
- **`amenities.osm_tags`** is an object of OSM tag → value (empty for non-OSM sites), and
  `shelter_kind` is `lean-to`, `tent site`, or `null`.

**Measured:** median **1.3 ms**, p95 1.5 ms over 50 enriched campsites (local, warm), with
~700-byte responses.

## Named routes (TM05-60)

Named hiking routes (OSM `route=hiking` relations, TM05-58), their elevation profiles
(TM05-59) and the campsites along them. Code: `backend/api/routes.py`.

### `GET /api/routes/?bbox=west,south,east,north`

Named routes whose geometry intersects the box, **longest first**, as a GeoJSON
FeatureCollection. Unnamed relations are not listed.

| Parameter | Default | Notes |
|---|---|---|
| `bbox` | required | Same format and validation as the layer endpoints |
| `limit` | 200 | Max 1000. `metadata.truncated` says whether more matched |
| `simplify` | none | Degrees, same as the layer endpoints. **Use `0.0001` for the map**: it cuts the High Peaks response from 384 KB to 141 KB |

A route is returned **whole**, including the part outside the box: a route clipped to the
viewport has the wrong length and profile.

```json
{
  "type": "FeatureCollection",
  "bbox": [-74.1, 44.05, -73.85, 44.25],
  "features": [
    {
      "type": "Feature",
      "id": 6619234,
      "geometry": {"type": "MultiLineString", "coordinates": [[[-73.962732, 44.182899], ...]]},
      "properties": {"osm_id": 6619234, "name": "Van Hoevenberg Trail", "ref": null,
                     "network": "lwn", "operator": "NYSDEC", "length_m": 12328.4}
    }
  ],
  "metadata": {"returned": 67, "truncated": false, "limit": 200, "simplify": null}
}
```

`length_m` is the sum of the main-line members (side branches excluded). It can exceed
the stitched line's length in the detail when a parallel branch is not part of the path —
Van Hoevenberg's 12,328 m includes the 972 m Marcy Dam bypass, while its stitched line is
11,373 m.

### `GET /api/routes/<osm_id>/`

| Parameter | Default | Notes |
|---|---|---|
| `campsites_within_m` | 500 | Campsites within this many metres of any route member. Capped at 5000; a non-integer is a 400 |

Unknown `osm_id` → 404.

```json
{
  "osm_id": 6619234,
  "source_id": "relation/6619234",
  "name": "Van Hoevenberg Trail",
  "ref": null, "network": "lwn", "operator": "NYSDEC",
  "length_m": 12328.4,
  "geometry": {"type": "MultiLineString", "coordinates": [...]},
  "line": {"type": "LineString", "coordinates": [[-73.962732, 44.182899], ...], "length_m": 11373.0},
  "path": {"parts": 2, "parts_used": 1, "parts_left_out": 1, "left_out_m": 971.7, "largest_join_gap_m": 0.0},
  "profile": {
    "status": "ok",
    "reason": null,
    "stats": {"length_m": 11373.0, "gain_m": 1007.4, "loss_m": 46.9, "high_m": 1627.6,
              "high_at_m": 11373.0, "low_m": 638.8, "low_at_m": 600.0, "start_m": 666.6,
              "end_m": 1627.6, "max_grade_pct": 33.0, "max_grade_at_m": 11125.0,
              "naive_gain_m": 1077.0, "naive_loss_m": 114.2},
    "distance_m": [0.0, 25.0, 50.0, ...],
    "elevation_m": [666.0, 665.1, ...],
    "params": {"spacing_m": 25, "smoothing_window_m": 100, "threshold_m": 3, "grade_window_m": 100},
    "source": {"name": "usgs-3dep", "datasets": ["NY_NH_Gaps_D24", ...], "resolution_m": [1],
               "vertical_datum": ["North American Vertical Datum of 1988 (NAVD 88)"],
               "computed_at": "2026-10-02T20:53:27.637233+00:00", "cached": true}
  },
  "campsites": {
    "within_m": 500,
    "count": 4,
    "truncated": false,
    "items": [
      {"id": "way/1305981156", "source": "osm", "name": "Marcy Dam Backcountry Campsites",
       "site_type": "primitive", "lon": -73.951989, "lat": 44.158017,
       "distance_along_m": 3773.1, "distance_from_route_m": 83.6,
       "score": 69, "score_breakdown": { "...": "a contract-1 score, docs/scoring.md" }}
    ]
  }
}
```

- **`line`** is the route stitched into one ordered path (docs/elevation.md). Draw the route
  from `geometry`. Use `line` for anything that moves *along* the route — the profile
  cursor, the map marker, the 3D camera. Positions in `profile.distance_m` and
  `distance_along_m` are measured along `line`.
- **`profile`** comes from the analysis cache. The first request for a route computes it
  from 3DEP (≈4–6 s); later requests read it (ms). If 3DEP is unavailable, `status` is
  `"unavailable"`, `reason` says why, `stats` and the series are absent, and **the rest of
  the response is still returned**.
- **`campsites.items[].display_name` / `display_name_derived`** (TM05-71): the same name the
  campsite detail endpoint gives the site. For an unnamed site that has been enriched, it is
  derived from nearby features ("Campsite near Calamity Brook") and flagged. An unenriched
  site falls back to its source `name`, which may be `null`. The trail list shows derived
  names in italics, as the campsite panel does.
- **`campsites.items[].position`** (TM05-73): `along`, `near_start` or `near_end`, with
  `position_label` "near the trailhead" or "near the trail's end", or `null` when along.
  A site past either end has no honest `distance_along_m`: it is 0 or the line's length.
  Show the label instead (docs/routes.md).
- **`difficulty`** (TM05-82): `{rating, label, shenandoah, formula, length_m, climb_m}`.
  `label` is Easy, Moderate or Hard, from Shenandoah's rating on the profile. It is `null`
  when the profile is unavailable. docs/routes.md has the bands.
- **`route_type`** (TM05-82): `{type, label, estimated, basis}`, where `type` is `loop`,
  `out_and_back` or `point_to_point`. A loop is measured (`estimated: false`). Every other
  type is estimated from what each end meets, and `basis` gives `ends_apart_m`, `start`
  and `end`. docs/routes.md explains it.
- **`campsites.items`** are ordered by `distance_along_m`, from
  `ST_LineLocatePoint(line, site) × length(line)`. `distance_from_route_m` is the
  perpendicular distance to the nearest route member. Both are metres in EPSG:5070
  (TM05-42), and the search uses the campsite `geom_m` index. At most 100 are returned
  (`truncated`).
- **`score` / `score_breakdown`** are the scoring engine's contract-1 result. The weather
  factor makes them change over time: do not cache longer than an hour.

### Measured (2026-10-02, local Docker PostGIS, median of 5 warm runs)

| Request | Time | Size |
|---|---|---|
| List, High Peaks box (67 routes) | 21 ms (first 247 ms) | 384 KB |
| List, High Peaks box, `simplify=0.0001` | 33 ms | 141 KB |
| List, whole Adirondack region, `simplify=0.0001` (200, truncated) | 234 ms | 752 KB |
| Detail, Van Hoevenberg, profile not yet cached | 5.7 s | 36 KB |
| Detail, Van Hoevenberg, cached (4 campsites) | 78 ms | 36 KB |
| Detail, `campsites_within_m=2000` (13 campsites) | 183 ms | 57 KB |

Most of a cached detail request is scoring the campsites, about 10 ms each.

---

## Trail search and the Discover list (TM05-74)

### `GET /api/routes/search/?q=&near=lon,lat&bbox=west,south,east,north&limit=25`

Code: `backend/api/route_search.py`. Give `q`, `bbox`, or both. Without either, the response
is **400**.

- **`q`** finds named routes whose name contains every word of the query, ignoring case
  and accents: `lac clair` finds "Lac Clâir Trail". It searches every named route, not just
  those in view.
- **`bbox`** without `q` is the Discover list: named routes in or near the view. "Near"
  means the bbox grown by 50% of its width and height on every side.
- **`near`** is the view centre. Results are ordered by distance from it, to each route's
  nearest point in metres, then by name. Without it they are ordered by name.
- **`limit`** defaults to 25, with a maximum of 100. `truncated` says there were more.

```json
{
  "query": "marcy",
  "count": 3,
  "truncated": false,
  "results": [
    {"osm_id": 7340133, "name": "Mount Marcy Trail", "length_m": 6593.6, "gain_m": 797.7,
     "centroid": [-73.9466, 44.1180], "distance_m": 3.1}
  ]
}
```

- **`gain_m`** comes from the route's cached elevation profile. It is `null` until the
  profile has been computed once, by opening the trail or by `build_route_profiles`. A
  search never calls 3DEP, so the list stays fast as the map moves.
- **An empty result** is `200` with `results: []`. The UI says "No named trails match …"
  or "No named trails in or near this view".

### Filters (TM05-85)

Filters narrow either list, and all of them combine. They are additional query parameters:

| Parameter | Meaning |
|---|---|
| `min_length_m`, `max_length_m` | The route's length, in metres |
| `min_gain_m`, `max_gain_m` | Its climb, in metres |
| `difficulty` | Any of `easy`, `moderate`, `hard`, comma-separated |
| `route_type` | Any of `loop`, `out_and_back`, `point_to_point` |
| `campsites_within_m` | A campsite within this many metres of the route (up to 2000) |

They read stored **RouteFacts**, one row per route in `enrichment`. The row is filled by
`manage.py enrich_routes <region>` (part of `make data`, after the route profiles) and
refreshed whenever a trail is opened.

- **Gain and difficulty need the route's profile.** A route without one cannot answer
  those filters. It is left out and counted in **`unknown`**, so the list can say "N trails
  have no elevation data yet".
- **Length always works.** Route type and "campsites within" need no profile.
- **Bad values** (an unknown difficulty, a negative number, text) return 400.

Measured on the dev DB: 70–150 ms warm; the first request of a process is slower, about
1.6 s.

## Trail for a clicked way (TM05-97)

### `GET /api/trails/<source_id>/trail/[?campsites_within_m=500]`

`source_id` is a trail way's id, for example `way/20074658`. The response has the same
shape as `GET /api/routes/<osm_id>/`, plus `assembled` and `assembly`:

- The way is a **route member**: that route's detail, with `assembled: false` and
  `assembly: null`.
- It is a **named way outside any route**: a trail assembled from the connected same-name
  ways (shared OSM nodes, or ends within 15 m). It comes with `assembled: true`,
  `osm_id: null`, `source_id: "assembled/way/<lowest member id>"` and
  `assembly: {from_way, ways, note}`.
- An **unnamed** or unknown way returns **404**.

docs/routes.md has the rules and the measurements.

## GPX export (TM05-79)

### `GET /api/routes/<osm_id>/gpx/[?campsites_within_m=500]`
### `GET /api/trails/<source_id>/gpx/[?campsites_within_m=500]`

These return a trail as a **GPX 1.1** file, for a GPS unit or a phone app. The response
headers are `Content-Type: application/gpx+xml` and
`Content-Disposition: attachment; filename="<trail-name>.gpx"`. The second form exports a
clicked way's trail, the same one `/trail/` returns, so assembled trails can be downloaded
too. The trail panel's **Download GPX** link uses whichever form fits the open trail.

The file is built from the same payload as the route detail, so it always matches the
panel. It holds three things, in the element order the schema requires:

| Element | Content |
|---|---|
| `<metadata>` | The trail name, a description (length, campsite distance, and "Elevation unavailable" when there is no profile), the export time (UTC), and the bounds. |
| `<wpt>` (one per campsite) | One for each campsite within `campsites_within_m` (default 500, maximum 5000), in order along the trail. Each has `lat`/`lon`, the campsite's display name as `<name>`, its score, legality verdict and position as `<desc>`, `<sym>Campground</sym>` and `<type>campsite</type>`. |
| `<trk>` | One `<trkseg>` holding the stitched route line. The points are the line's vertices plus the elevation profile's sample points, merged in order along the trail. |

The `<trk>` points carry `<ele>` (metres, NAVD88, from 3DEP), linearly interpolated from
the stored profile. When the profile is unavailable, `<ele>` is left out, which GPX allows.

**Coordinate order.** GPX writes latitude first, as `lat="44.18" lon="-73.96"` attributes.
GeoJSON, used everywhere else in this API, writes longitude first. tests/test_gpx.py checks
the order against known points.

**Validation.** Every document in tests/test_gpx.py is validated against the official GPX
1.1 schema. A copy is vendored at tests/fixtures/gpx-1.1.xsd, unchanged from
topografix.com (sha256 `9e4d1988…f34d6`). The validator is the test-only `xmlschema`
package; writing GPX uses only the standard library.

**Measured (2026-10-08).** For the Van Hoevenberg Trail (`/api/routes/6619234/gpx/`, 11.4
km, with a stored profile), the export took 0.5 s and produced 69 KB: 862 track points,
all with elevation, and 8 campsite waypoints. It passed schema validation.

Errors:
- **400** for a bad `campsites_within_m`.
- **404** for an unknown route, or an unnamed or unknown way.

## Custom waypoints (TM05-80)

A signed-in user's own points on the map: a water source, a planned camp, a bail-out, or
anything else. They live in the `planning` app, and every waypoint belongs to one user.

| Method and path | What it does | Success |
|---|---|---|
| `GET /api/waypoints/` | The user's waypoints, oldest first | 200, a list |
| `POST /api/waypoints/` | Create one: `{name, kind, note?, lon, lat}` | 201, the waypoint |
| `GET /api/waypoints/<id>/` | One waypoint | 200 |
| `PATCH /api/waypoints/<id>/` | Change any of `name`, `kind`, `note`, `lon`, `lat` | 200, the waypoint |
| `DELETE /api/waypoints/<id>/` | Delete it | 204 |

A waypoint looks like this:

```json
{"id": 1, "name": "Brook camp", "kind": "camp", "kind_label": "Camp",
 "note": "Flat spot by the brook", "lon": -73.964725, "lat": 44.169079,
 "created_at": "2026-10-08T04:29:36Z", "updated_at": "2026-10-08T04:29:39Z"}
```

Field rules:
- `kind` is one of `water`, `camp`, `bailout` or `custom` (the default).
- `name` is required, and is trimmed, with at most 80 characters.
- `note` is optional, with at most 2,000 characters.
- `lon` must be in −180..180 and `lat` in −90..90 (WGS84).
- An invalid field returns **400** with DRF's `{field: [messages]}`.
- A user can keep at most 1,000 waypoints. Past that, **400** with `{error}`.

**Authentication** is `Authorization: Token <key>`, as for saved campsites (docs/auth.md).
With no token, or a bad one, every endpoint returns **401**.

**Isolation.** Every query is filtered by the signed-in user, and the owner is never taken
from the request body. Another user's waypoint id returns **404**, the same as an id that
doesn't exist. A 403 would confirm that the id exists. Deleting an account deletes its
waypoints, through the CASCADE foreign key.

**In GPX exports.** `GET /api/routes/<osm_id>/gpx/` and `/api/trails/<source_id>/gpx/`
accept the same token, and it is optional there. When it is present, the user's own
waypoints within `campsites_within_m` of the trail are added as `<wpt>` elements. That is
the same distance the campsites use. Each one has `<name>`, the note as `<desc>`, and
`<type>waypoint:<kind></type>`, plus a Garmin-style `<sym>`:

| kind | sym |
|---|---|
| water | Drinking Water |
| camp | Campground |
| bailout | Trail Head |
| custom | Flag, Blue |

A signed-out download has no user waypoints. The trail panel's Download GPX link sends
the token when the user is signed in.

**On the map**, each waypoint has a marker coloured by kind (the `--waypoint-*` tokens in
theme.css) with its own glyph: a drop, a tent, an arrow or a flag. Under the layer panel,
"My waypoints" has **+ Add**: the next map click drops a draft and opens the editor.
Clicking a marker reopens the editor to rename, retype, edit the note or delete.

## Not included yet

**Scored campsites in the map layers.** The layer endpoints above return raw ingested
features. Scores are served per campsite by the campsite detail (TM05-45), and the route
detail carries scores for the campsites along a route.
