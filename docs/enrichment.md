# Campsite enrichment (TM05-64)

A campsite as ingested is a point and, often, nothing else: 350 of the 563 Adirondack
campsites have no name. The facts that describe a site already exist in our other tables
and in 3DEP, so `enrich_campsites` derives them and stores them beside the campsite.

```
python manage.py enrich_campsites adirondacks
```

## Where facts live, and why there

The facts are stored in `enrichment.CampsiteFacts`, one row per campsite (a one-to-one
keyed on the campsite), with `computed_at`, `method_version` and `provenance`.

They are **never written into `Campsite`**:
- `Campsite` holds what the source said, and the next ingest overwrites it.
- Facts are what we *worked out*. They can be recomputed and are versioned and dated.

Every fact field is nullable or blank, because unknown is not zero. The detail endpoint
returns `null` for an unknown fact, and the UI hides it rather than printing "Unknown".

The command is idempotent: a re-run updates each row.

## The facts

| Fact | How | Fields |
|---|---|---|
| Public land unit | The **smallest** PAD-US parcel containing the site, by `ST_Area(geom::geography)`: a wilderness inside the Forest Preserve rather than the Preserve. Depends on TM05-57's repaired parcels. | `land_name`, `land_manager`, `land_designation`, `land_access`, `land_gap_status`, `land_source_id` |
| Nearest named water | KNN on `geom_m` (TM05-42) over water with a GNIS name, within 5 km. The NHD adapter copies the name into `name`. The raw payload is read as a fallback in both casings: flowlines (layer 6) use `gnis_name`, waterbodies (layer 12) use `GNIS_NAME`. All 17,225 named rows have the name in both places today. | `water_name`, `water_distance_m`, `water_feature_type`, `water_perennial`, `water_source_id` |
| Nearest named trail | Nearest named hiking **route** (TM05-58) and nearest named OSM **way**, each within 5 km. The route wins unless the way is more than 100 m closer. Route members *are* ways, so on a route the two are usually the same distance, and the route name is what a hiker uses. | `trail_name`, `trail_distance_m`, `trail_kind` (`route` / `way`), `trail_source_id` |
| Elevation and slope | The `site_terrain` analysis: USGS 3DEP (the TM05-59 sampler) at a 3×3 stencil 10 m apart, with slope by Horn's method, in degrees and percent. | `elevation_m`, `slope_deg`, `slope_pct` |
| OSM tags | OSM tags the campsite adapter does not already read into `Campsite`: `operator`, `description`, `tents`, `fireplace`, `openfire`, `toilets`, `drinking_water`, `shower`, `fee`, `access`, `dog`, `camp_site`, `caravans`, `cabins`, `power_supply`, `opening_hours`, `wheelchair`, `website`, `phone`, `ref`. `shelter_kind` is `lean-to` (`shelter_type=lean_to`) or `tent site` (`tents=yes`). | `osm_tags`, `shelter_kind` |
| Display name | The source name if there is one. Otherwise "Campsite near *X*", where *X* is the nearest named water or trail within 1 km; otherwise "Campsite in *land unit*". **Derived names are flagged.** | `display_name`, `display_name_derived` |

### Why the slope stencil is 10 m

The stencil spans 20 m across, which is campsite scale: a tent pad and the ground around it.
A smaller stencil reads rocks and roots in 1 m LiDAR as slope. A larger one blends in the
hillside the site was cut into. Horn's method is the weighted 3×3 finite difference that
GIS slope rasters use; the formula is in `analysis/analyses/terrain.py`.

**Caveat.** 3DEP is hydro-flattened, so a site whose mapped point sits on a pond reads
exactly 0°. 24 of the 563 do, including Marcy Dam.

### Shared with scoring

The scoring engine's slope factor (docs/scoring.md) reads the same `site_terrain` cache,
so an enriched campsite never waits on 3DEP when scored.

`Analysis.canonical_params()` makes `{}`, `{"stencil_m": 10}` and `{"stencil_m": 10.0}`
one cache key. Before that, scoring missed every entry enrichment had written and called
3DEP for each site; a regression test now covers it.

### Batching

`Analysis.run_many()` does one cache lookup for all sites and calls `compute_many()` for
the misses. For terrain that is 9 points per site in 400-point 3DEP requests, about 44
sites per request.

## Measured: Adirondacks, 563 campsites (2026-10-02)

| Run | Time |
|---|---|
| Cold (3DEP for every site) | **145.4 s**, of which terrain 134.8 s |
| Warm re-run (terrain cached) | **10.4 s** (terrain 0.1 s) |

| Fact | Coverage |
|---|---|
| Public land unit | 505 (89.7%) |
| Named water (≤ 5 km) | 563 (100.0%) |
| Named trail (≤ 5 km) | 556 (98.8%): 218 routes, 338 ways |
| Elevation + slope | 563 (100.0%) |
| Any OSM tag | 220 (39.1%). Most common: operator 136, description 78, fee 48, tents 47 |
| Shelter kind | 45 (8.0%) |
| Display name | 562 (99.8%), derived for 349 of the 350 unnamed sites |

**Slope:** median 4.8°, 90th percentile 11.9°, max 46.4°. 142 sites are steeper than 8°,
27 steeper than 15°, and 24 read 0° (water).

**Most common land units:**

| Unit | Campsites |
|---|---|
| Saranac Lakes Wild Forest | 100 |
| High Peaks Wilderness | 84 |
| Lake George Islands Campground | 44 |
| Saint Regis Canoe Area | 43 |

### Score distribution (563 Adirondack campsites)

Weather is excluded so the stages are comparable, since the forecast changes hourly.
"Before TM05-57" is reconstructed by scoring legal status against only the parcels that
existed before the repair re-ingest: rows created before 2026-10-02 23:20 UTC, which is
2,299 parcels, exactly the pre-repair count.

| Stage | Median | Mean | Stdev | Min / max | In a parcel |
|---|---|---|---|---|---|
| Before TM05-57 (slope not scored) | 56 | 57.9 | 16.37 | 0 / 98 | 176 |
| After TM05-57 (slope not scored) | 78 | 75.3 | 14.42 | 0 / 99 | 505 |
| After TM05-64 (slope scored) | 77 | 75.0 | 13.09 | 0 / 99 | 505 |
| After TM05-64, live weather included | 79 | 76.4 | 11.42 | 0 / 96 | 505 |

TM05-57 moves the median by 22 points: campsites were being scored as "probably private"
on public land. Scoring slope barely moves the median, because most sites are on gentle
ground. It does pull down the 27 sites on steep ground and tightens the spread.
