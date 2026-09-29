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
`permanent_identifier` for water, and so on. It is stable across re-ingests, so it is safe
to use with `map.setFeatureState()`.

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

## Not included yet

**Scoring.** These endpoints return raw ingested features, not scored campsites. The
0–100 score is a later story.
