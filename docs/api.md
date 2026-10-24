# Map data API

Written for the frontend. Everything here except the vector tiles returns GeoJSON you can hand straight to
MapLibre as a source — no reshaping needed.

The server runs at `http://localhost:8000` by default (`python manage.py runserver` from
`backend/`). All endpoints are GET, need no authentication, and CORS is already open to
the Vite dev server on port 5173. Endpoints that return scores also accept an optional
`Authorization: Token <token>`: signed in, campsites are scored with that user's own
weights ([Scoring weights](#scoring-weights-tm05-46)).

---

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/campsites/` | Campsites — points |
| `GET /api/trails/` | Trails — MultiLineStrings |
| `GET /api/water/` | Streams, rivers, lakes, ponds, wetlands — LineStrings and Polygons |
| `GET /api/public-land/` | Public land parcels and legal access — MultiPolygons |
| `GET /api/peaks/` | Peaks, with elevation — points (TM05-89) |
| `GET /api/trailheads/` | Trailheads — points (TM05-89) |
| `GET /api/map-data/` | The first four at once, for the initial load; peaks and trailheads on request with `layers=` |
| `GET /api/tiles/<layer>/<z>/<x>/<y>.mvt` | Trails, water and public land as Mapbox Vector Tiles, which is what the map draws them from. See [Vector tiles](#vector-tiles-tm05-140) |
| `GET /api/campsites/<id>/detail/` | One campsite with its derived facts — see [Campsite detail](#campsite-detail-tm05-64) |
| `GET /api/campsites/<id>/viewshed/` | What the terrain lets you see from a campsite — see [Terrain facts](#terrain-facts-tm05-142) |
| `GET /api/routes/` | Named hiking routes in a bbox — see [Named routes](#named-routes-tm05-60) |
| `GET /api/routes/<osm_id>/` | One route: stats, elevation profile, campsites along it with scores |
| `GET /api/saved-campsites/` | The signed-in user's saved campsites, with names, scores and land units — see [Saved campsites list](#saved-campsites-list-tm05-87) |
| `GET`/`PUT`/`DELETE /api/auth/me/weights/` | The signed-in user's factor weights — see [Scoring weights](#scoring-weights-tm05-46) |

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

Comma-separated subset of `campsites,trails,water,public-land,peaks,trailheads`.
Defaults to the first four.

`peaks` and `trailheads` (TM05-89) are opt-in: they are returned only when named, for
example `layers=campsites,peaks,trailheads`, so the default first paint is unchanged. A
peak carries `name` and `elevation_m` (metres, `null` when OpenStreetMap has no usable
`ele`); a trailhead carries `name`. Either name may be empty.

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
| `score` | int \| null | 0–100, the same score the campsite detail panel shows (TM05-86). `null` when not scored — never 0 |
| `score_status` | string | `scored`, `pending` (not enriched yet), or `not_available` (enriched, but no weighted factor could be evaluated) |

The score is the campsite detail endpoint's, computed by the same code from stored values
only, so the map and the panel never disagree. No request calls 3DEP or Open-Meteo:

- Water, trail access, legal status and land cover are the results `enrich_campsites`
  stores with each site's facts (docs/scoring.md, "Stored factor results").
- Slope and weather are read from the analysis cache, as on the panel; a miss is
  `not_available` and the weights renormalise.

Only the features the cap keeps are scored, so the cap, the deterministic sample and the
truncation metadata are exactly as before. The other three layers have no score.
Check `score` for `null` before colouring on it: `null` is "no score", not a low one.

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

**The map no longer meets the cap for trails, water or public land.** Since TM05-140 it
draws those three layers from [vector tiles](#vector-tiles-tm05-140), which are never
capped. Only campsites still come from `/api/map-data/`, so a "showing X of Y" notice
can now only be about campsites. The GeoJSON endpoints keep their cap for any other
caller.

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

**Campsite scores (TM05-86).** Measured on the restored dev snapshot (563 enriched
Adirondack campsites) through the Django test client, local PostGIS 16 on WSL2, best and
median of 5 warm runs. Script and raw output: `artifacts/tm05-86/`.

| Viewport | Before (no score) | Scored per request | Stored factor results (shipped) |
|---|---|---|---|
| Adirondack Park (regions.yml), 563 sites | 8 ms, 1 query | 17,141 ms, 3,943 queries | **1,256 ms** (median 1,706), 1,128 queries |
| High Peaks, 33 km, 52 sites | 3 ms, 1 query | 762 ms, 366 queries | **119 ms** (median 146), 106 queries |

Scoring each site from scratch spends ~36 ms of its ~43 ms in the water factor's nearest
searches, which is why those results are stored. What remains is two analysis-cache
lookups per site (slope, weather); batching them is the next step if the zoomed-out map
needs to be faster. The first request after the factor settings change recomputes the
stored results it touches (about 17 s for the whole park), unless `enrich_campsites` has
been re-run first.

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
campsite's score (TM05-45), the same score the map's campsite features carry (TM05-86).
- **Unknown facts are `null`,** never placeholder text, so the UI can hide them.
- **`facts` is `null`** for a campsite that hasn't been enriched yet; today that's
  everything outside the Adirondacks.
- **The score uses stored values only.** This request never calls 3DEP or Open-Meteo.
  Water, trail access, legal status and land cover are the factor results
  `enrich_campsites` stores with the facts (TM05-86); the map's campsite layer combines
  the same ones, so the two always show the same score. Slope and weather come from the
  analysis cache that `enrich_campsites` and other requests fill. An input
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
  weather is scored only when the forecast for that grid cell was already fetched in the
  last hour. When it is `not_available`, the weights are
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
       "score": 69, "score_status": "scored",
       "score_breakdown": { "...": "a contract-1 score, docs/scoring.md" }}
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
- **`score` / `score_status` / `score_breakdown`** are exactly the campsite detail's
  (TM05-72): scored from stored values only, so the trail list, the detail panel and the
  marker colour never disagree. An unenriched site is `pending`, with `score` and
  `score_breakdown` null, and no 3DEP or Open-Meteo call is made for the list. The weather
  factor makes a score change over time: do not cache longer than an hour.

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

## Overnight plans (TM05-81)

An overnight plan is a set of campsites along one trail, chosen as nightly stops. The API
returns each day's distance, gain and loss. Plans live in the `planning` app and belong to
one user. Authentication and isolation work exactly as for waypoints: every endpoint takes
`Authorization: Token <key>` and returns **401** without one. Another user's plan returns
**404**.

| Method and path | What it does |
|---|---|
| `POST /api/plans/preview/` | Work out a plan without saving it (the trail panel calls this on every change) |
| `GET /api/plans/[?osm_id=…\|?from_way=…]` | The user's plans, newest first, optionally for one trail: `{id, name, osm_id, from_way, trail_name, nights, created_at, updated_at}` |
| `POST /api/plans/` | Save one. **201** with the worked-out plan |
| `GET /api/plans/<id>/` | Reopen one, worked out against its trail as it is now |
| `PATCH /api/plans/<id>/` | Change `name` and/or `stop_ids`. An invalid change is rejected and changes nothing |
| `DELETE /api/plans/<id>/` | **204** |
| `GET /api/plans/<id>/gpx/` | The plan as GPX 1.1 |

**Request body**: `{"osm_id": 6619234, "stop_ids": ["node/…", "node/…"], "name": "…"}`.
- `osm_id` names a route. For a trail assembled from segments (TM05-97), use
  `from_way: "way/…"` instead, and for a route planned across connected trails (TM05-119),
  `planned_route: "<route id>"` ([Planned routes](#planned-routes-tm05-119)). The list
  filters by any of the three.
- `stop_ids` are campsite ids, in any order.
- `name` is optional, up to 120 characters. It defaults to "<trail>: N nights".

**Worked-out plan**, the shape of preview, create, read and update:

```json
{"trail": {"osm_id": 6619234, "source_id": "relation/6619234", "name": "Van Hoevenberg Trail", "length_m": 11372.9},
 "nights": 2,
 "stops": [{"night": 1, "id": "node/…", "display_name": "Phelps Brook Lean-to", "lon": …, "lat": …,
            "distance_along_m": 2931.8, "distance_from_route_m": 13.5, "score": 79,
            "legality": {"verdict": "permitted", "label": "Permitted · designated site", …},
            "warning": null}, …],
 "days": [{"day": 1, "from": "Start", "to": "Phelps Brook Lean-to", "start_m": 0, "end_m": 2931.8,
           "distance_m": 2931.8, "gain_m": 62.7, "loss_m": 30.9}, …],
 "totals": {"distance_m": 11372.9, "gain_m": 1010.3, "loss_m": 49.8},
 "profile": {"status": "ok", "reason": null},
 "warnings": []}
```

Saved plans also carry `id`, `name`, `osm_id`, `from_way`, `trail_name` and the
timestamps.

**Ordering.** Stops are put in order by their position along the route's stitched line,
whatever order they were sent in. Night *n* is the *n*-th stop from the route's start. A
plan runs in the route's own direction, the same direction as the trail panel's miles and
profile.

**Rejected stops** return **400** with `{"error": "<sentence>"}`, naming the campsite:
- A campsite past either end of the route. "Off the end" uses the same rule as the trail
  list (`routes.yml`, `along`): more than 100 m from the line, and within 50 m of an end.
  For example: "Wilderness Campground at Heart Lake is off the end of Van Hoevenberg
  Trail: it lies before the trail's start, 151 m from the trail. Choose a campsite along
  the trail."
- A campsite more than 5 km from the route.
- No stops, the same campsite twice, an unknown id, or more than 30 stops.
- A body that names no trail. An unknown trail returns **404**.

**Days.** A plan with N stops has N+1 days: start → stop 1 → … → stop N → end.
- A day's distance is measured along the stitched line between stop positions.
- Gain and loss come from the route's **stored** elevation profile, the one the trail
  panel computed when the trail was first opened. If no profile is stored yet, it is
  computed once and stored.
- The profile is smoothed over its whole length with the route's own 100 m window. Each
  day's slice is then counted with the same 3 m threshold, so a one-day plan reports
  exactly the route's gain and loss.
- Across several days, the threshold restarts at each stop, so the days' sums can differ
  from the route figure by up to about 3 m per stop. The Van Hoevenberg Trail with 2
  stops: 3,306 ft against the route's 3,305 ft.
- When the profile is unavailable, days have distance only (`gain_m`/`loss_m` null), and
  `profile.status` is `unavailable`.

**Legality.** Every stop carries its legality verdict (docs/scoring.md). A stop that isn't
"permitted" gets a `warning`, also collected in `warnings`, for example: "Night 2,
Campsite near Van Hoevenberg Trail: Unknown: check current rules. Not a designated site
we can confirm. …". The trail panel shows each stop's verdict beside its day, and lists
the warnings above the table.

**GPX** (`/api/plans/<id>/gpx/`) contains:
- the route's track, with elevations, as in TM05-79
- each stop as a `<wpt>` named "Night N: <campsite>", with `<type>overnight-stop</type>`
  and its day's distance, climb and verdict in `<desc>`
- the user's own waypoints within 500 m of the trail (TM05-80)

General campsites that aren't stops are left out, so the file is the trip itself. The
file name is the plan's name, for example `marcy-dam-overnight.gpx`.

**In the trail panel**, signed in, each campsite along the trail has a **+ Night** button
(disabled for sites past the trail's ends). The Overnight plan section above the list
shows:
- the day table, with totals and warnings
- Save or Update, and Download plan GPX
- "Your plans for this trail", each with Open and Delete

Signed out, the section offers sign-in.

## Potential campsites (TM05-99)

### `GET /api/routes/<osm_id>/candidates/[?campsites_within_m=500]`
### `GET /api/trails/<source_id>/candidates/[?campsites_within_m=500]`

These return computed **potential campsites** along a trail: points that pass every hard
filter of NY's rules for camping away from a designated site, scored, spread at least
0.5 mi apart, and at most 8. The method, honesty rules and measurements are in
docs/candidates.md. Answers are cached per route, corridor and config: the first request
for a trail can take 15–35 s (3DEP), and later ones about 5 ms.

```json
{"status": "ok", "within_m": 500, "cached": false, "compute_ms": 19208,
 "counts": {"sampled": 570, "passed": 31, "scored": 13, "kept": 3,
            "rejected": {"public_land": 44, "trail": 71, "water": 44, "elevation": 207,
                         "terrain": 0, "slope": 173}},
 "reason": null,
 "candidates": [{
   "id": "candidate/-73.963412,44.171280", "kind": "candidate",
   "label": "Potential spot (unverified)",
   "lon": -73.963412, "lat": 44.17128, "distance_along_m": 1300.2,
   "distance_from_route_m": 60.0, "side": "left", "score": 98,
   "confidence": {"level": "computed", "label": "Computed", ...},
   "checks": [{"key": "public_land", "passed": true, "label": "On public land with open access (High Peaks Wilderness)."}, ...],
   "not_checked": "Road distance isn't checked; verify current rules on the ground.",
   "rule": {"text": "Camping is prohibited within 150 feet of any road, trail, ...", "source": "https://dec.ny.gov/..."},
   "elevation_m": 669.1, "slope_deg": 0.6, "nearest_trail_m": 60.0, "nearest_water_m": 87.0,
   "score_breakdown": {...}}]}
```

**Fields:**
- `reason` is a sentence explaining an empty result, and null otherwise.
- `score_breakdown` is the scoring engine's contract-1 result, without weather.
- **When 3DEP fails:** `status: "unavailable"` with a `reason`, and no candidates.

**Errors:**
- **400** for a bad `campsites_within_m`.
- **404** for an unknown route, or an unnamed or unknown way.

**Candidates as plan stops (TM05-81).** A candidate's `id` can be sent in a plan's
`stop_ids` beside campsite ids. Such a stop comes back with:
- `kind: "candidate"`
- `display_name` "Potential spot (unverified)"
- an `unknown` legality labelled the same
- the unverified-stop `warning`

**Terrain (TM05-143).**

- **The pooling check.** Each candidate's `checks` include `pooling`: "Not in a high water
  pooling risk zone (terrain model)." Where `make terrain` hasn't run, it reads "Water
  pooling risk not checked: no terrain data here yet."
- **Rejections.** `counts.rejected.pooling` counts the points the zones removed.
- **Badges.** Each candidate carries
  `"terrain": {"pooling": null, "shelter": "exposed" | null, "water_view": null}`: only
  what the zones can say about a point with no site facts. docs/candidates.md explains why.
- **Scoring.** Campsite scores (model 1.3.0) gain the optional `drainage`, `shelter` and
  `view` factors (docs/scoring.md). They appear in `score_breakdown` like any other factor.

## Saved trails (TM05-100)

| Method and path | What it does | Success |
|---|---|---|
| `GET /api/saved-trails/` | The user's saved trails, newest first: `{id, osm_id, from_way, name, length_m, created_at}` | 200 |
| `POST /api/saved-trails/` | Save one: `{"osm_id": 6619234}` for a route, or `{"from_way": "way/…"}` for an assembled trail (TM05-97) | **201**; saving the same trail again returns **200** with the existing row |
| `DELETE /api/saved-trails/<id>/` | Unsave it | 204 |

**How it works:**
- **Authentication and isolation** work as for waypoints and plans: a token is required
  (**401** without one), and another user's id returns **404**.
- **Resolving the trail.** The trail is resolved when saved, so the Profile view lists its
  name and length without opening every trail. A way that belongs to a route is saved as
  that route.
- **Bad and unknown trails.** **400** for a body that names no trail or a bad `osm_id`.
  **404** for an unknown route or way.

The trail panel's **Save trail** button uses these endpoints. The **Profile** view
(`/profile`, linked from the header when signed in) lists saved campsites, saved trails,
waypoints and overnight plans in tabs. It replaces the floating Saved panel.

- **Opening an item.** Clicking an item goes to the map, flies there, and opens its panel:
  - a campsite: the campsite panel, with the raised pin
  - a trail: the trail panel
  - a waypoint: its editor
  - a plan: its trail, with the plan loaded

  This works whatever layers are on.
- **Campsite names.** Saved campsites show the campsite detail endpoint's
  `display_name`, so derived names appear too. The saved-campsites list endpoint is
  unchanged (TM05-87).

## Connecting trails in the route detail (TM05-101)

`GET /api/routes/<osm_id>/` and `GET /api/trails/<source_id>/trail/` include
`connections`. These are the named trails that share a junction node with this one, in
order of the first junction along this trail:

```json
"connections": [
  {"name": "Marcy Dam Truck Trail", "osm_id": 6619273, "way_id": null,
   "junctions": [{"node_id": 2178563123, "lon": -73.9551, "lat": 44.1576, "distance_along_m": 2752.3},
                 {"node_id": 2178563170, "lon": -73.9512, "lat": 44.1542, "distance_along_m": 3698.0}]},
  {"name": "Old Marcy Dam Trail", "osm_id": null, "way_id": "way/371777637", "junctions": [...]}
]
```

Open a route by its `osm_id`, or an assembled trail by its `way_id` (TM05-97). The rules
are in docs/routes.md.

## Discover trails: browsing a region (TM05-102)

The **Discover trails** page (`/trails`, in the header) browses with the same
`GET /api/routes/search/` endpoint as the map's search (TM05-74), with the same filters
(TM05-85). It adds these parameters:

| Parameter | Meaning |
|---|---|
| `region=adirondacks` | Routes inside a region of `backend/pipeline/regions.yml`: the route's bounding box overlaps the region's box. A long route such as the Appalachian Trail is in every region it crosses. An unknown region returns **400**, listing the regions that exist. |
| `sort=distance\|length\|gain\|name` | `distance` (the default when `near` is given) is metres from `near` to the route. `length` and `gain` sort the longest or the most climbing first, with unknown gain last. `name` is the default without `near`. `sort=distance` without `near` returns **400**. |
| `offset=24` | The next page, used with `limit` (at most 100). The response has `total` (every match), `offset`, `truncated` (more after this page), `sort` and `region`. |
| `cards=1` | Adds card data to each result (below). |

Each result's card data:
- `difficulty` and `route_type` (with `route_type_estimated`), from the stored RouteFacts
- `sparkline`: up to 32 elevations (m) averaged from the **stored** profile, or null when
  none is stored. It is never computed here.
- `campsites`: mapped campsites within `campsites_within_m` (500 m), counted in one indexed
  query per page

### `GET /api/regions/`

The regions in `regions.yml`, for the page's selector: `{id, label, bbox, states, trails}`.
`trails` is the number of named routes in the region's box. The page lists regions with
no trails yet as disabled.

**Measured.** A 24-card page of the Adirondacks sorted by gain took 0.4 s.

**The page.**
- **Region and sort.** The region choice is remembered in the browser. "Distance from map
  view" measures from the map's last centre when it is inside the region, otherwise from
  the region's centre.
- **Paging.** Results come 24 at a time with **Show more**.
- **Opening.** A card opens the map with that trail's panel, which fits the view to the
  trail.

## Saved campsites list (TM05-87)

`GET /api/saved-campsites/` (token required, documented in [auth.md](auth.md)) lists the
signed-in user's saved campsites, and only theirs. Each entry carries the same
`display_name`/`display_name_derived`, `score`/`score_status` and `public_land` as the
campsite detail above, from the same helpers in `api/campsite_detail.py`, plus flat
`latitude`/`longitude`. The score uses the user's own weights when they have saved some.

## Scoring weights (TM05-46)

A signed-in user can set how much each factor counts. Scores then use those weights
wherever that user's token is sent: the campsite detail, the campsite map features
(`/api/campsites/`, `/api/map-data/`) and the campsites along a route
(`/api/routes/<osm_id>/`, `/api/trails/<source_id>/trail/`). Signed out, or with no saved
weights, scores use the defaults in `scoring/config.yml`.

Only the weights are personal. Curves, caps and the legal gate stay the shipped config's,
so a user changes what matters to them, not what a factor measures. Every score still
reports each factor's `weight` and `effective_weight` in its breakdown, and its
`config_digest` changes with the weights, so a personal score is never mistaken for a
default one.

| Method | Body | Returns |
|---|---|---|
| `GET /api/auth/me/weights/` | — | `200`, the caller's weights |
| `PUT /api/auth/me/weights/` | `{"weights": {"water": 0.5, "slope": 0.2}}` | `200`, the saved weights |
| `DELETE /api/auth/me/weights/` | — | `204`, back to the defaults |

All three need `Authorization: Token <token>`; without it, `401`. Each acts on the token's
own user, and there is no user id in the URL, so no request can read or change another
user's weights.

```json
{
  "weights":  {"water": 0.5, "legal": 0.3, "trail": 0.2, "weather": 0.15, "slope": 0.2, "land_cover": 0.05},
  "defaults": {"water": 0.35, "legal": 0.3, "trail": 0.2, "weather": 0.15, "slope": 0.1, "land_cover": 0.05},
  "custom": true
}
```

- **`weights`** is the complete set the user's scores use. Factors left out of a `PUT` keep
  the default weight. A later `PUT` replaces the earlier one; it does not merge with it.
- **`custom`** is `false` when the user has saved nothing, and `weights` then equals
  `defaults`.
- Weights are relative and need not sum to 1, exactly as in `config.yml`.

**Validation.** Weights go through the same `scoring.config.parse()` check as `config.yml`,
plus three more. A rejected `PUT` changes nothing and returns `400` with a reason:

| Problem | `error` contains |
|---|---|
| `weights` missing, empty, or not an object | `must be an object of factor to number` |
| A key that is not a factor | `unknown factor(s): ...`, plus the list of factors |
| A value that is not a number (strings, `true`, `null`, lists) | `must be a number` |
| A negative number | `must be a number >= 0` |
| `NaN` or an infinite number | `must be a finite number`, or a JSON parse error |
| Every weight zero | `at least one weight must be above 0` |

**Tokens on the public endpoints.** On the scoring endpoints a missing, revoked or
malformed token is treated as signed out (default weights), not as `401`. A map should not
stop loading because its token was revoked in another tab.

Stored factor results (TM05-86) do not depend on weights, so personal weights cost nothing
extra per request.

## Recorded hikes (TM05-111)

A hike is recorded in the browser and sent **once, when the hiker chooses Save**. No
endpoint takes a position while a hike is in progress. How the numbers are worked out is
in docs/tracking.md.

| Method and path | What it does | Success |
|---|---|---|
| `GET /api/hikes/` | The user's hikes, newest first, **without** their tracks | 200 |
| `POST /api/hikes/` | Save a finished hike (body below) | **201**, with the hike and its track |
| `GET /api/hikes/<id>/` | One hike, with its `track` | 200 |
| `DELETE /api/hikes/<id>/` | Delete it | 204 |
| `GET /api/hikes/<id>/gpx/` | The hike as GPX 1.1: one `<trkseg>` per recorded segment, a `<time>` on every point, `<ele>` where one was sampled | 200, `application/gpx+xml`, as an attachment |

The POST body:

```json
{
  "name": "Hike on Van Hoevenberg Trail",
  "mode": "trail",
  "simulated": false,
  "osm_id": 6619234,
  "from_way": null,
  "trail_name": "Van Hoevenberg Trail",
  "elapsed_s": 13980,
  "moving_s": 12710,
  "distance_m": 11402.5,
  "gain_m": 868.4,
  "track": [[[-73.962732, 44.1829, 663.2, 1791043200000], ...], [...]]
}
```

- **The track.** `track` is a list of segments, each a list of
  `[lon, lat, elevation_m or null, unix_ms]`. A new segment begins wherever the recording
  had a gap: a pause, or the page hidden. Times must never go backwards. At most 40,000
  points and 500 segments are allowed, and at least one segment needs two points.
- **What is stored.** `started_at` and `ended_at` are taken from the track's own first and
  last times. The track is also stored as a 4326 MultiLineString with a spatial index. The
  numbers are stored as sent, which is what the display showed.
- **Mode.** `mode` is `trail` or `free`. A free hike keeps no trail fields.
- **Limits and errors.** Each user can keep up to 500 hikes. A bad body or track returns
  **400** with `{"error": "..."}`.
- **Authentication and isolation** work as for waypoints and plans: a token is required
  (**401** without one), and another user's hike returns **404** on every endpoint.
  Deleting the account deletes its hikes.

## Planned routes (TM05-119)

A route across connected trails, through points the user picks. `docs/routing.md`
explains the graph, the costs and the engine.

| Method and path | What it does |
|---|---|
| `POST /api/routing/plan/[?campsites_within_m=500]` | Snap the points to the trails and route through them |
| `GET /api/routing/<route id>/[?campsites_within_m=500]` | The same route again, by its id |
| `GET /api/routing/<route id>/candidates/[?campsites_within_m=500]` | Potential campsites along it ([TM05-99](#potential-campsites-tm05-99)) |
| `GET /api/routing/<route id>/gpx/[?campsites_within_m=500]` | GPX 1.1, as for a trail ([TM05-79](#gpx-export-tm05-79)) |

All four are public. Signed in, campsite scores use the user's weights, and the GPX adds
the user's own waypoints, as for a trail.

**Request** (`POST /api/routing/plan/`):

```json
{"points": [[-73.9581, 44.1832], [-73.9235, 44.1127], [-73.9581, 44.1832]], "cost": "naismith"}
```

- `points`: `[lon, lat]`, start first and end last, 2 to 10 of them. Stops between are
  visited in order. Each snaps to the nearest point on a trail segment within 1 km, all
  on one connected piece of the network (TM05-137, `docs/routing.md`).
- `cost`: `naismith` (default: quickest by Naismith's rule) or `distance` (shortest).

**Route id**: `<region>:<cost>:<stop>,<stop>,...`. A stop is `w<way>-<decimetres>` (a
point that far along OSM trail way `<way>`), or an OSM node id at a junction. For
example: `adirondacks:naismith:w1509987586-4120,2306094170`. It re-solves to the same
route while the trails are unchanged. TM05-119's all-node ids still work.

**Response**: the route detail of [`GET /api/routes/<osm_id>/`](#get-apiroutesosm_id),
with `osm_id: null`, `source_id: "planned/<digest>"` and `name: "Route via …"`, plus:

```json
"planned": {
  "id": "adirondacks:naismith:2306094170,4252860218,2306094170",
  "region": "adirondacks",
  "cost": "naismith",
  "stops": [{"token": "w1509987586-4120", "node_id": null, "lon": -73.958, "lat": 44.183, "trail_name": "Van Hoevenberg Trail", "snapped_m": 12.4}, …],
  "legs": [{"from": "…", "to": "…", "length_m": 11372.9, "ascent_m": 1051.2, "descent_m": 61.0, "naismith_s": 14495}, …],
  "trails": [{"name": "Van Hoevenberg Trail", "kind": "trail", "length_m": 11372.9},
             {"name": "Blue Ridge Road", "kind": "road walk", "length_m": 67.2}, …],
  "off_trail": {"road_walk_m": 67.2, "track_m": 0.0, "bridged_m": 3.1},
  "graph_totals": {"length_m": …, "ascent_m": …, "descent_m": …, "naismith_s": …},
  "timing_ms": {"snap": 31.2, "graph_load": 0.4, "graph_was_cached": true, "search": 18.9,
                "assemble": 6.1, "nodes_settled": 4210, "total": 512.0}
}
```

- `snapped_m` is click to vertex, and `null` when the route was opened from its id.
- `trails` lists everything the route uses, in the order it first reaches it, with the
  distance on each. `kind` is `trail`, `track`, `road walk` (a road or sidewalk between
  trails), or `gap bridged` (a few metres the map leaves between two trails that meet).
  Unnamed ones read "Unnamed path", "Unnamed track", "Unnamed road" or "Gap between mapped
  trails".
- `off_trail` totals how much of the route leaves trail (TM05-137).
- `stops[].node_id` is `null` for a stop between junctions.
- `graph_totals` are the graph's own (50 m samples). The panel's stats are the profile's,
  as for any trail.

**Errors**: **400** for a bad `campsites_within_m`. **422** with `{"error": "…"}` when
the request can't be routed:
- a point is more than 1 km from any trail
- the points aren't on one connected network. The error names the nearest point where a
  connected route is possible, and the body adds
  `"suggestion": {"lon", "lat", "trail_name", "distance_m", "instead_of": "start" | "stop"}`.
- consecutive stops of a route id aren't connected ("The trails don't connect A to B …")
- a route id names a node no longer on the graph
- there is no graph built for the region yet

**404** for a path that isn't a route id.

## Vector tiles (TM05-140)

### `GET /api/tiles/<layer>/<z>/<x>/<y>.mvt`

Trails, water and public land as [Mapbox Vector Tiles](https://github.com/mapbox/vector-tile-spec)
2.1, built per request by PostGIS `ST_AsMVT` (code: `backend/api/tiles.py`).

- **Layers.** `layer` is `trails`, `water` or `public-land`. Each tile holds one MVT
  layer of that name, so a MapLibre layer's `source-layer` is the same string.
- **Zooms.** `z` runs from 0 to 14. Beyond 14 the endpoint returns **404**, and MapLibre
  overzooms the z14 tile (the source's `maxzoom` is 14). At 4,096 units across, a z14
  tile already resolves under a metre in the Adirondacks.
- **Empty tiles.** A tile with nothing in it, or one below the layer's minimum zoom, is a
  **204** with no body. MapLibre treats that as an empty tile.
- **Other errors.** An unknown layer, `x` or `y` outside 0…2^z−1, or `z > 14` is a 404.
- **Headers.** `Content-Type: application/vnd.mapbox-vector-tile` and
  `Cache-Control: public, max-age=3600, stale-while-revalidate=86400`. Tiles change only
  when an ingest runs. Responses are gzipped when the browser accepts it.
- **No authentication.** Nothing in a tile depends on the user. Campsites stay on
  `/api/map-data/` because their colours come from the signed-in user's weights.
- **Feature ids.** Each feature's id is the row's integer primary key; MVT ids must be
  integers. The string id the trail panel fetches by (`"way/123"`) is the `source_id`
  attribute, where `sourceIdOf()` already reads it.

#### What each layer carries, by zoom

| Layer | From zoom | Rows | Attributes |
|---|---|---|---|
| `trails` | 9 | all | `source_id`, `name`, `trail_type`, `length_m` at every zoom: a trail is clickable wherever it is drawn |
| `water` | 9 | Zooms 9–10: lakes, wetlands and perennial streams. From 11: every intermittent or unknown-flow stream too. | `source_id`, `name`, `feature_type`, and from zoom 12 `perennial` |
| `public-land` | 0 | all | `source_id`, `name`, `public_access`, and from zoom 10 `manager`, `designation`, `gap_status` |

**Geometry handling.**

- **Simplified at low zoom.** Below zoom 13 (12 for public land), geometry is simplified
  to half a tile pixel. From there up, the only loss is ST_AsMVTGeom's snap to the
  4,096 grid.
- **Clipped before reprojecting.** Each geometry is cut to the tile, with a 64-unit
  buffer, before it is transformed. A PAD-US parcel that spans the country costs one
  tile's worth of work.
- **No seams.** The same buffer keeps lines and polygon edges continuous where tiles
  meet.

#### Adding a layer

1. Add a `TileLayer` to `TILE_LAYERS` in `backend/api/tiles.py`:

   ```python
   "peaks": TileLayer(
       name="peaks",
       model=Landmark,
       minzoom=10,
       attributes=((0, ("source_id", "name")), (12, ("elevation_m",))),
       thin=((12, "elevation_m > 1200"),),  # optional: below zoom 12, only the high ones
   ),
   ```

   The model needs an SRID 4326 `geom` with a spatial index; every model in `geodata`
   has one. `thin` conditions are constant SQL on the model's columns.
2. On the frontend, add the layer and its minzoom to `TILED` in
   `frontend/src/map/tileLayers.ts`, plus a `LAYERS` entry and draw layers in
   `map/layers.ts`. Give each draw layer `"source-layer": "<name>"`.
3. Add a test beside `tests/test_api_tiles.py`'s attribute-per-zoom tests.

#### Measured: before and after (2026-10-23)

The method:

- Local dev servers, headless Chrome at 1440×900, with a fresh browser profile per
  session, so nothing is cached.
- Each session opens the app located at its centre (zoom 12) and zooms with the keyboard
  to its target. It ends when no layer request has been in flight for 3 s.
- **Data** is the on-the-wire (gzipped) bytes of layer-data responses for the whole
  session: `/api/map-data/` before, `/api/tiles/` after.
- **Load** is from the last zoom step (for High Peaks, from the first layer request) to
  the last layer response.
- Each session ran three times. The medians are below, with the range in brackets.

| Session | Before: data | Before: load | After: data | After: load | What the map shows |
|---|---|---|---|---|---|
| Adirondacks overview, z8 | 651 KB (502–651), 1–2 requests | 1.68 s (1.57–2.49) | 442 KB (366–541), 26–53 tiles | 0.46 s (0.41–1.98) | Before: 1,000 of 1,742 public-land parcels, with a notice. After: all 1,742. |
| High Peaks, z12 | 98 KB, 1 request | 1.23 s (0.76–1.32) | 119 KB, 36 tiles | 1.02 s (0.65–1.06) | The same features. |
| Marcy Dam, z15 | 173 KB, 2 requests | 0.46 s (0.44–0.46) | 87 KB, 42 tiles | 0.06 s (0.03–0.75) | The same features. Zooming from 12 to 15 reuses the z12–14 tiles already loaded. |

Tiles also revisit for free: a pan back, or a zoom back out, is served from the browser
cache with no request at all. The GeoJSON path re-requested any viewport that missed its
40-entry cache. A cold tile costs 1–10 ms of database time from zoom 11 up, and
50–160 ms for the densest zoom 9 tiles (`tests/test_api_tiles.py` covers correctness,
not timing).

## Terrain facts (TM05-142)

These come from the terrain pipeline (`make terrain`, docs/terrain-analysis.md). They are
precomputed, so they cost nothing per request.

### In `GET /api/campsites/<id>/detail/`: `terrain`

```json
"terrain": {
  "pooling": {"level": "low", "reason": "Water drains away from here (wetness index 7.2)."},
  "sun": {"facing": "southeast", "label": "morning and midday sun"},
  "shelter": {"level": "moderate", "reason": "About level with the ground around it."},
  "view": {"area_km2": 7.1, "direction": "all around", "water": true},
  "has_viewshed": true,
  "note": "Terrain-model estimate from bare-earth elevation. Trees, buildings and recent changes aren't counted.",
  "computed_at": "2026-10-24T01:45:53Z"
}
```

Each part is null when that fact is unknown; `view.direction` and `view.water` can be null
on their own. `terrain` itself is null for a campsite `make terrain` hasn't reached. The
values the app shows:

| Field | Values |
|---|---|
| `pooling.level` | `low`, `medium` or `high` |
| `sun.facing` | `north`, `northeast`, `east`, … or `flat` |
| `shelter.level` | `sheltered`, `moderate` or `exposed` |
| `view.direction` | a compass sector, or `all around` |
| `view.water` | 1 ha or more of lake or pond visible within 2 km |

Show `note` with them: the model sees bare earth only.

### `GET /api/campsites/<id>/viewshed/`

What the terrain lets you see from the site (eye height 1.7 m, out to 10 km), as a GeoJSON
Feature: a MultiPolygon in EPSG:4326, simplified to 15 m. Its properties are `area_km2`,
`direction`, `water_view` and `note`. It is a separate request because the outline is the
one large part, and the panel only needs it on "Show what I can see". It returns **404**
when the site has no viewshed.

### On a route's campsite rows: `terrain`

Each item of `campsites.items` in `GET /api/routes/<osm_id>/` and
`GET /api/trails/<source_id>/trail/` carries the compact form for badges:

```json
"terrain": {"pooling": "high", "shelter": "sheltered", "water_view": false}
```

It is null for a campsite without terrain facts.

### Map layers

`/api/tiles/pooling-risk/…` and `/api/tiles/exposure/…` serve the zones, with the
`zone_class` attribute, from zoom 8. See [Vector tiles](#vector-tiles-tm05-140).

## Not included yet

**Scores on the trail, water and public-land layers.** Only campsites are scored. Campsite
features carry `score` and `score_status` (TM05-86, [Properties](#properties)), the same
score as the campsite detail (TM05-45).
