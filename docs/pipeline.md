# The ingestion pipeline

This document has two readers in mind: a teammate who needs to run an ingest and
understand what came back, and whoever writes the fifth source adapter. If you only want
the commands, section 2 is enough.

For *why* the pipeline is shaped the way it is — why we persist vector data but query
imagery on demand — see [architecture.md](architecture.md). This document is about
operating it.

---

## 1. What it does

The pipeline fetches geographic data from outside services, converts it into CampSite's
own vocabulary, and stores it in PostGIS so the app can ask spatial questions quickly.
Four sources are live: public land boundaries, hiking trails, water features, and federal
campsites.

Every source follows the same three-step contract, and only the first two are ever written
by hand:

**`fetch(aoi)`** pulls raw data for one area of interest. It returns whatever shape the
service gives back — a list, or a generator yielding pages as they arrive.

**`normalize(raw)`** converts that into dictionaries whose keys are model field names. It
receives exactly what `fetch` returned, so a generator stays a generator and a large
source is never held in memory all at once.

**`load(records)`** is framework code. No adapter implements it. It reprojects geometry,
validates it, promotes a single geometry into a Multi container where the column needs
one, writes rows in batches, and records what happened.

An adapter therefore declares four attributes and writes two methods. Everything else —
reprojection, deduplication, upserting, provenance, batching, optional tiling, retry with
backoff — is handled once, in the framework, for every source.

---

## 2. Running an ingest

### Prerequisites

The PostGIS container has to be running and Django has to know how to reach it:

```
docker compose up -d
```

`DATABASE_URL` must be set in the repo-root `.env`. If it is missing Django refuses to
start with an explicit message rather than silently falling back to SQLite. See
[setup.md](setup.md) for the full first-run instructions, including the GDAL library paths
macOS needs.

One source needs a credential. `ridb` reads `RIDB_API_KEY` from the same `.env`; the other
three need nothing. Keys are free — register at
<https://ridb.recreation.gov/profile>, then copy the value into `.env` (which is
gitignored; only `.env.example` is committed). Without it the adapter fails immediately
with a clear message rather than part-way through a run.

### The commands

Everything runs through one management command, from the `backend/` directory:

```
python manage.py ingest --list-sources
python manage.py ingest --list-regions
python manage.py ingest <source> <region>
```

The command knows nothing about any particular source. It looks the name up in the adapter
registry and the region up in `pipeline/regions.yml`, so a newly written adapter appears
automatically. An unknown name lists what is available instead of failing obscurely.

### The sources

| Source | Writes to | What it returns |
|---|---|---|
| `padus` | `PublicLand` | Land ownership and legal camping access, from the USGS Protected Areas Database |
| `osm-trails` | `Trail` | Hiking trails from OpenStreetMap, with ordered node IDs preserved |
| `osm-routes` | `TrailRoute` | Named hiking routes (OSM `route=hiking` relations): ordered member ways, one geometry, total length |
| `nhd-flowlines` | `WaterFeature` | Streams and rivers from USGS NHD |
| `nhd-waterbodies` | `WaterFeature` | Lakes, ponds, reservoirs and wetlands from USGS NHD |
| `ridb` | `Campsite` | Federal campsites from Recreation.gov |
| `osm-campsites` | `Campsite` | Backcountry campsites from OpenStreetMap |

Naming follows one rule: a source that yields a single dataset gets its bare name
(`padus`, `ridb`), and a source yielding several gets `source-dataset` (`osm-trails`,
`nhd-flowlines`). OSM also has campsites and NHD has two layers, hence the suffixes.

### What a healthy run looks like

These are real figures from full ingests, useful as a sanity check. If your run returns
roughly these numbers, it worked; if it returns a fraction of them, something is wrong.

| Command | Rows loaded | Skipped | Status |
|---|---|---|---|
| `ingest padus adirondacks` | 1,574 | 149 | partial |
| `ingest osm-trails adirondacks` | 18,067 | 0 | success |
| `ingest nhd-flowlines adirondacks` | 46,589 | 0 | success |
| `ingest nhd-waterbodies adirondacks` | 16,818 | 3 | partial |
| `ingest ridb white-mountains-nh` | 660 | 64 | partial |
| `ingest osm-campsites adirondacks` | 563 | 0 | success |

Two things worth noticing. Three of the five finish *partial*, and that is the normal
outcome — see section 4. And `ridb` is run against the White Mountains rather than the
Adirondacks on purpose, which section 6 explains.

Across the two NHD runs the perennial split comes out at 49,348 year-round, 13,618
intermittent or ephemeral, and 441 where the source does not say. That last number
matters: it is recorded as *unknown*, not as *not perennial*.

---

## 3. Reading the output

The command prints a one-line summary, but the durable record is the `IngestRun` table.
Every run writes one row before fetching anything and updates it at the end.

A run is created with status **failed** and only promoted on success. If the process is
killed halfway, the row says failed rather than claiming a success that never finished.

**success** means every record the source returned was written.

**partial** means some records were skipped and the rest were written. The reasons are in
`notes`, one line per skipped record, truncated after twenty with a count of the
remainder. Partial is not an error; it usually means the upstream data has known defects.

**failed** means the run raised. Nothing is half-loaded — `load()` runs inside a
transaction, so a failure rolls back every batch.

To see what happened:

```sql
SELECT source, region, status, record_count, started_at
FROM geodata_ingestrun
ORDER BY started_at DESC LIMIT 10;
```

and for the detail of a partial run:

```sql
SELECT notes FROM geodata_ingestrun WHERE status = 'partial' ORDER BY started_at DESC LIMIT 1;
```

One wrinkle: both NHD adapters write `source = 'nhd'`, because the source is the same
database. To tell a flowline run from a waterbody run, look at the parameters:

```sql
SELECT source, parameters->>'layer_id' AS nhd_layer, record_count
FROM geodata_ingestrun WHERE source = 'nhd';
```

Layer 6 is flowlines, layer 12 is waterbodies.

Every row also points back at the run that last wrote it, so provenance is answerable per
record and not just per run:

```sql
SELECT count(*) FROM geodata_trail WHERE last_run_id = 42;
```

or through the ORM, where the region is reachable across the link:

```python
Campsite.objects.filter(last_run__region="white-mountains-nh")
```

Deleting an old run nulls that link rather than deleting the data — pruning run history
must never remove ingested rows.

### Re-running is safe

Every source has a stable key, `(source, source_id)`, enforced by a unique constraint.
Running the same ingest twice updates the existing rows instead of duplicating them, and
re-stamps them with the newer run. There is no need to clear a table first, and no harm in
running an ingest you are not sure completed.

---

## 4. Why partial runs are normal

Some sources finish partial. In each case the framework validated something the source got
wrong, skipped that record, and said so.

**Invalid geometry is repaired, not skipped (TM05-57).** PAD-US ships about 9% of its
Adirondack parcels with self-intersecting rings or nested shells — digitizing artifacts in
the federal dataset. They used to be skipped, which silently dropped the High Peaks
Wilderness and the White Mountain National Forest; for a model that decides where camping
is *legal*, a missing parcel is a wrong answer. `load()` now repairs any invalid geometry
with PostGIS `ST_MakeValid`, then keeps only the parts the target column can hold
(`ST_CollectionExtract`): a repair that returns a polygon plus a stray line keeps the
polygon. Only geometry with nothing usable left after repair is skipped, as
"not repairable". Every repair is listed in the run notes under "Repaired with
ST_MakeValid". The repair runs in the database rather than local GEOS so it is judged by
the same library that validates the stored row.

Measured on 2026-10-02, re-ingesting PAD-US:

| | Before | After |
|---|---|---|
| Adirondacks run | `partial`, 1,574 written, 149 skipped | `success`, 1,723 written, 149 repaired, 0 skipped |
| White Mountains run | `partial`, 727 written, 49 skipped | `success`, 776 written, 49 repaired, 0 skipped |
| Parcels in the table | 2,299 | 2,488 (0 invalid) |
| High Peaks Wilderness | absent | present: 1,114 km², open, GAP 1 |
| Campsites inside any parcel | 199 of 1,320 | **1,174 of 1,320** |

**NHD waterbodies** used to skip 3 of 16,821 for the same reason; the next run repairs
them too.

**RIDB skips 64 of 724 campsites** because they have no usable coordinates. Recreation.gov
publishes some sites with blank or literal `0, 0` coordinates, and zero-zero is a point in
the Gulf of Guinea rather than a campsite. Those records are skipped and counted rather
than stored at a fictional location.

`osm-trails` and `nhd-flowlines` return clean data and finish successful.

---

## 5. Adding a new source

Write one file in `backend/pipeline/adapters/`, subclass `SourceAdapter`, decorate it with
`@register`, and add it to the import line in `adapters/__init__.py`. Nothing else in the
project changes — not the base class, not the registry, not the management command.

**`padus.py` is the best adapter to read first.** It is the shortest, it uses the shared
ArcGIS client rather than hand-rolling HTTP, and it documents a genuinely hard decision
(synthesizing an identifier) in a way the others do not need to.

### What you must declare

```python
@register
class MySourceAdapter(SourceAdapter):
    name = "mysource"           # registry key and CLI argument
    source = Model.Source.MINE  # the SourceRecord.Source value stamped on each row
    model = MyModel             # which geodata model to write
    source_srid = 4326          # the projection the source delivers
```

and implement `fetch(aoi)` and `normalize(raw)`.

### What you get for free

- **Reprojection** to EPSG:4326 from whatever `source_srid` you declare. You never call
  `transform` yourself.
- **Geometry validation**, with invalid records skipped and the reason recorded.
- **Single-to-multi promotion**, so a `LineString` can go into a `MultiLineString` column.
  Do not do this in `normalize` — it is already handled.
- **Idempotent upsert** on `(source, source_id)`, batched 1,000 rows at a time.
- **Provenance**: the `IngestRun` row, the record count, the status, and the `last_run`
  link on every record.
- **Optional tiling.** Set `max_tile_degrees` and the framework splits the area into a
  grid, calls `fetch` once per tile, and deduplicates features that straddle a boundary.
  Leave it unset and `fetch` is called once with the whole region.
- **Retry with backoff** via `pipeline/retry.py`, if you route your HTTP through it.
- **Streaming.** Return a list if the source is small; yield if it is large. Both work.

### What you have to decide

**Your `source_id` strategy.** This is the most important decision and the easiest to get
wrong. It must identify the same real-world thing across runs and across upstream
releases. If the source has a stable identifier, use it (`osm-trails` uses the OSM way ID,
NHD uses `permanent_identifier`). If it does not, you will have to synthesize one — see
the PADUS notes below for what that costs.

**Your field mapping**, including how to classify things honestly. Where the source has no
opinion, map to unknown or null rather than guessing. `None` and `False` are different
facts and the scoring model treats them differently.

**Whether tiling is needed**, and at what size. Measure rather than copy: the existing
three tiled adapters landed on different sizes for different reasons, all documented in
their module docstrings.

**Whether to filter server-side.** `nhd-flowlines` passes a `where` clause that drops
canals and pipelines, cutting volume 41% and improving data quality at once.

### Testing a new adapter

Record fixtures from a real response rather than hand-writing them, so the tests break when
the payload shape changes and not only when your reading of it does. Keep them small — a
handful of features covering each branch. Scrub any credential before saving.

Add one `@pytest.mark.network` test that runs the real adapter against a small real area.
See section 7.

---

## 6. Per-source notes

Things we learned the hard way, worth knowing before touching any of these.

**PADUS has no stable identifier.** Two candidate fields are dead: `BndryID` is the literal
string `"Not Applicable"` for every row, and `ST_Name` has exactly one distinct value
nationally. `OBJECTID` is not stable across service republishes. So `source_id` is a
SHA-256 hash of the unit name, designation, manager and a centroid rounded to four decimal
places. The recipe deliberately excludes full geometry: PAD-US re-digitizes boundaries
between releases, so hashing the shape would mint a new identifier for the same real parcel
and orphan the old row. It would also be coordinate-dependent, so changing the requested
projection would rotate every identifier at once.

**NHD returns different field casing per layer.** Flowlines come back lowercase
(`fcode`, `gnis_name`); waterbodies come back uppercase (`FCODE`, `GNIS_NAME`). Same
service, same release. Reading the wrong case yields `None` rather than an error, which
would quietly write null names into the database, so every lookup goes through a
case-folding helper.

**NHD was retired in October 2023.** It is still served and queryable but frozen and no
longer maintained. We target it anyway rather than its successor, the 3D Hydrography
Program, because 3DHP classifies flowlines topologically — Canal, Channel Line, Connector
— and has no perennial/intermittent equivalent. That distinction feeds the campsite score
directly, so moving to 3DHP would silently cost a scoring input. Worth revisiting if 3DHP
gains a flow-regime attribute.

**OSM trail ingestion filters out urban pedestrian infrastructure.** The first Adirondack
ingest returned 26,005 "trails", and roughly 30% of them were not trails: 7,471 sidewalks
and street crossings, plus 548 golf cart paths. In and around Saranac Lake and Lake Placid
the backcountry map was largely street furniture. The query now excludes them server-side,
so they are never transferred, and `is_hiking_trail()` applies the same rule again to
whatever comes back.

Excluded:

| Rule | Why |
|---|---|
| `footway` in `sidewalk`, `crossing`, `traffic_island`, `access_aisle` | These four values are what make a `highway=footway` urban. A crossing is a painted line over a road; a sidewalk runs beside one. |
| any `golf` tag | Cart paths, tagged `highway=path` or `footway`. |

Deliberately **not** excluded, each of which looked tempting and is wrong:

| Candidate | Why it was rejected |
|---|---|
| `tiger:*` tags | 2,578 ways carry them, but 2,573 are not urban — 2,154 are `highway=track`, 958 are named, 51 carry `sac_scale`. Adirondack forest roads and logging tracks came in through the US Census import, and they are exactly the approach routes this project wants. |
| requiring `sac_scale` | Only 758 of 26,005 ways are graded. Requiring a grade would discard 97% of the network, most of it real trail. Absence means nobody graded it, not that it is pavement. |
| `informal=yes` | 650 herd paths. Unofficial but genuinely walked, and often the only route up a trailless High Peak. |

`highway=footway` itself stays in the query. Near trailheads and huts a real trail segment
is frequently just `highway=footway` with nothing else on it, so excluding the value
wholesale would lose real trail — which is why the filter keys on the *subtag* instead.

Each run records `excluded_footway_values` and `excluded_if_tagged` in its `parameters`,
so a row count is interpretable against the filter that produced it.

**Overpass requires a User-Agent** and rejects requests without one using HTTP 406, which
is not retryable. The public instance allows two concurrent slots, so the client retries
with backoff rather than assuming a request will succeed. On overload Overpass serves an
HTML error page with HTTP 200, so a client that assumes a 200 body is JSON fails far from
the cause.

**RIDB's `radius` is in miles and silently clamps at 25.** Asking for 30, 40 or 1000
returns exactly the same results as 25. This is why tiling is mandatory for RIDB rather
than an optimisation: the Adirondacks alone are roughly 104 by 131 miles and would need a
circumscribing radius of about 84. At 0.5 degrees a tile fits inside a 25-mile circle with
about 15% margin. RIDB is also the only source queried by circle rather than bounding box,
so the circle over-fetches roughly 27% beyond the tile and results are filtered back to the
tile in `normalize`.

**Campsites come from two sources, and that is not redundancy.** RIDB covers Forest
Service and Park Service land; the Adirondacks are New York State Forest Preserve, so RIDB
returns essentially nothing there. Before `osm-campsites` existed the database held 660
campsites in the White Mountains and 92,000 trails and water features in the Adirondacks,
three hundred kilometres apart, and **no viewport anywhere on the map showed a campsite and
a stream at the same time**. Adding OSM campsites is what made one region complete: the
Adirondacks now hold 563 campsites alongside 18,067 trails, 63,407 water features and
1,574 public land parcels.

The two sources share the `Campsite` table and stay distinct by `source_id` namespace --
RIDB writes `campsite/73996`, OSM writes `node/4270946202` or `way/32002985`. That matters
beyond tidiness: `/api/saved-campsites/<source_id>/` resolves a campsite by `source_id`
alone, so a collision between the two would be a wrong-site bug.

`osm-campsites` asks Overpass for `out center` rather than `out geom`, because a campsite
way is an area you pitch inside and the model stores one Point. Relations are not ingested,
for the same reason `osm-trails` skips `route=hiking` relations: a `tourism=camp_site`
relation groups ways the query already returns, so ingesting it would duplicate sites
rather than add them. Each run records its queried `element_types` in `parameters`.

Site type is mapped narrowly. `backcountry=yes` (153 of 230 sampled High Peaks features)
becomes `primitive`, `group_only=yes` becomes `group`, a lean-to shelter becomes `lean_to`,
and **everything else stays `unknown`**. `tourism=camp_site` on its own says somebody
mapped a camping spot, not that it is a developed campground, so promoting the residual to
`designated` would assert something the source never said.

**RIDB is federal-only.** It covers Forest Service and Park Service land and knows nothing
about state land. Adirondack Park is New York state land, so running `ingest ridb
adirondacks` returning almost nothing is correct behaviour, not a bug. Adirondack campsite
coverage comes from OpenStreetMap instead. Use `white-mountains-nh` when you want to see
RIDB actually work — the White Mountain National Forest is USFS.

---

### osm-routes (TM05-58)

`TrailRoute` is what a hiker means by a trail. `osm-trails` stores OSM *ways* — segments
between junctions, roughly 40% unnamed — while a `route=hiking` relation groups ways under
one name: the Van Hoevenberg Trail, the Northville-Placid Trail. Each row keeps the
relation id (`osm_id`, and `source_id` = `relation/<id>`), `name`, `ref`, `network`,
`operator`, `member_way_ids` in relation order (joining to `Trail.source_id` as
`way/<id>`), a MultiLineString with one line per main-line member, the metric `geom_m`
column, and `length_m`.

- **One query per region.** `relation["route"="hiking"](bbox); out geom;` returns every
  member's coordinates inline. Tiling would transfer a long route once per tile, so the
  adapter sets `max_tile_degrees = None`.
- **Side branches** (roles `alternative`, `excursion`, `approach`, `connection`) stay in
  `member_way_ids` but are left out of `geom` and `length_m`, so the length is the route
  rather than the route plus its spurs. A way listed twice counts once.
- **Nested relations are not expanded.** A super-relation (the Appalachian Trail is made of
  per-state section relations) has no way members of its own; it is skipped with "missing
  geom" in the run notes, and its sections are ingested in their own right. Expect the
  Adirondack run to be `partial` with exactly this one skip (relation/20254765).
- **The whole route is stored**, including any part outside the region box, because a
  route's length and profile mean nothing clipped.

Measured on 2026-10-02:

| Region | Relations | Response | Time | Ingested |
|---|---|---|---|---|
| Adirondacks | 271 | 5.0 MB | 8 s (raw curl) / 4.4 s (ingest) | 270, 1 skipped (super-relation) |
| White Mountains | 182 | 3.0 MB | 38 s with two Overpass 504 retries / 3.0 s on a later run | 182 |

Re-running upserts by relation id: three Adirondack runs left the table at 452 rows.

**Coverage**, from `python manage.py route_coverage`:

| Region | Routes | Trail length on a named route | Ways on a named route |
|---|---|---|---|
| Adirondacks | 270 | 1,318 of 11,143 km (**11.8%**) | 940 of 18,067 (5.2%) |
| White Mountains | 182 | 961 of 5,240 km (**18.3%**) | 583 of 7,596 (7.7%) |

So named routes are the backbone, not the network: the main marked trails are covered, but
most ingested way length — logging tracks, unmarked herd paths, connector paths — is on no
route. Routes also add very few names to unnamed ways (0.7% of unnamed Adirondack ways are
on a route), because unnamed ways are mostly not part of marked routes in the first place.
Anything that needs "the trail this segment belongs to" for every segment will still need
way-level fallbacks.

## 7. Integration tests against live services

Each source has one test that runs the real adapter against a small real area, hits the
live service, and asserts on the rows that landed in PostGIS. They are marked `network`
and **deselected by default**, so an upstream outage can never turn CI red.

To run them deliberately:

```
pytest -m network
```

`ridb`'s test needs `RIDB_API_KEY` set; the rest need only the database. They use
deliberately tiny bounding boxes — a single valley in most cases — because these are free
public services and Overpass in particular has only two shared slots.

The default `pytest` run excludes them, which is what CI executes.

---

## 8. Limitations

**The loader never deletes.** `load()` upserts and nothing else, so a feature removed
upstream lingers in our table indefinitely. Nobody notices until a parcel that no longer
exists influences a score. Reconciliation — working out what is in our table but no longer
in the source — is not built.

**Distances need a geography cast.** Geometry is stored in EPSG:4326, so a plain
`ST_Distance` returns degrees of arc rather than metres, and inconsistently: one degree of
longitude is about 79 km at Adirondack latitude against 111 km for one degree of latitude.
Scoring queries must cast to geography (`geom::geography`) or pass `spheroid=True`. This is
a query-time concern only; storage is unaffected.

**Trail lengths are approximate.** `length_m` is computed with the haversine formula over a
sphere rather than the WGS84 ellipsoid, because OSM does not tag length and adding a
projection library for one function was not worth it. Measured against PostGIS
`ST_Length(geography)` on real Adirondack trails the error is under 0.25% worst case and
about 0.13% typically — roughly 18 metres on a 15-kilometre trail.

**Invalid source geometry is skipped, not repaired.** See section 4. For PADUS this means
about 9% of parcels are absent from the table.
