# Terrain analysis with GeoLibre (TM05-139 spike)

This spike asked whether GeoLibre can compute campsite terrain facts on our server:
drainage and pooling, aspect, shelter, and viewshed. It also had to find the Adirondacks
elevation source, and which resolution each tool can afford.

**Decision: go.** geolibre-wasm runs server-side in our Python 3.12 environment. Every
tool we need is in its open tier, under MIT and Apache-2.0 licences. The terrain
pipeline (TM05-141) builds on it, using the tools and resolutions below.

The raw measurements are in `artifacts/terrain/spike/*.jsonl`, one JSON line per tool run.

## What GeoLibre is

[geolibre-wasm](https://pypi.org/project/geolibre-wasm/) 1.7.1 runs a single WebAssembly
module, `geolibre-cli.wasm`, in-process through
[wasmtime](https://github.com/bytecodealliance/wasmtime-py). The module is the
whitebox_next_gen tool suite plus GeoLibre's own tools.

- **No native install, no server, no GDAL.** It is just `pip install`.
- **A sandboxed `/work`.** Each call runs over a private temporary directory mounted as
  `/work`. Input files are copied in, and any new files come back as `bytes`.
- **1,062 tools.** `list_tools()` and `list_manifests()` list them: 732 from Whitebox
  and 330 from GeoLibre.

| | Version | Licence |
|---|---|---|
| `geolibre-wasm` (Python wrapper) | 1.7.1 | MIT |
| `wasmtime` (its only dependency) | 49.0.0 | Apache-2.0 WITH LLVM-exception |
| `geolibre-cli-v1.7.1.wasm` (the tools) | v1.7.1 | built from [opengeos/geolibre-rust](https://github.com/opengeos/geolibre-rust) (MIT) and [opengeos/whitebox-wasm](https://github.com/opengeos/whitebox-wasm) (Apache-2.0) |
| whitebox_next_gen engine (inside the WASM) | | dual MIT / Apache-2.0 (`LICENSE-MIT`, `LICENSE-APACHE`) |

**The licensing allows our use.**

- whitebox_next_gen's README says its proprietary paid extension (`wbtools_pro`) "exists
  outside this OSS workspace". The WASM is built only from the open crates (`wbcore`,
  `wbtools_oss`).
- All 1,062 manifests report `license_tier: "open"`.
- Nothing we use needs a licence key or an account.

### Installing it, and pinning the runtime

`geolibre-wasm==1.7.1` is in `requirements.txt`.

On first use, the wrapper downloads `geolibre-cli-v1.7.1.wasm` (24,111,247 bytes) from the
GitHub release. **It does not check a checksum**, so we don't let it download:

1. Fetch the release asset once, outside the repository. TM05-141 uses
   `~/.cache/campsite/geolibre/`.
2. Check it against the release's `SHA256SUMS.txt`:

   ```
   1bbd170210e1c25fc76f4edeccc68ea9ceb34fbf141cea48d68172fd4e34feca  geolibre-cli-v1.7.1.wasm
   ```

3. Point `GEOLIBRE_WASM` at the checked file.

The WASM is never committed.

Compiling the 24 MB module takes about 3 s and 870 MB of RSS per process. A
`wasmtime.Module.serialize()` cache next to it, also outside git, brings that down to
0.01 s and 68 MB. The cache is tied to the wasmtime version, so it is rebuilt when that
changes.

## It runs server-side

Every tool below ran under `.venv` (CPython 3.12.15, macOS arm64). It runs the same way on
CI's Ubuntu, because wasmtime ships manylinux wheels. Outputs are GeoTIFFs (COG) that keep
the input CRS, here EPSG:5070. Vector outputs are GeoJSON in WGS84.

**Spot check.** Slope over the 3 km Marcy Dam box agrees with `gdaldem slope`: a mean of
17.44° against 17.37°, and a maximum of 62.86° against 62.86°.

## Tools for each campsite question

`listTools` and the manifests give these candidates. The choice made for each is explained
under [Resolutions](#resolutions-chosen-and-why).

| Question | Candidate tools | Chosen |
|---|---|---|
| Slope | `slope` (Zevenbergen-Thorne) | Already stored per site (TM05-64, `site_terrain`); not duplicated |
| Aspect / sun | `aspect` | `aspect` |
| Drainage, water pooling | `fill_depressions`, `breach_depressions_least_cost`, `d8_flow_accum`, `dinf_flow_accum`, `fd8_flow_accum`, `wetness_index` (TWI), `depth_in_sink`, `sink` | `fill_depressions` → `dinf_flow_accum` (SCA) → `wetness_index`, plus `depth_in_sink` |
| Shelter / exposure | `deviation_from_mean_elevation` (DEV), `relative_topographic_position`, `openness`, `geomorphons`, `exposure_towards_wind_flux`, `sky_view_factor` | `deviation_from_mean_elevation` |
| What you can see | `viewshed` (per station), `visibility_index`, `skyline_analysis` | `viewshed`, one station per site |
| Cold-air pooling (TM05-147) | `elevation_percentile`, `relative_topographic_position`, `sky_view_factor`, `depth_in_sink` | `elevation_percentile` |
| Exposure to the prevailing wind (TM05-148) | `fetch_analysis`, `exposure_towards_wind_flux` | `fetch_analysis` |
| Hours of direct sun, morning sun (TM05-162) | `time_in_daylight`, `solar_radiation`, `horizon_angle`, `shadow_image` | `time_in_daylight` |
| Zones as polygons | `reclass`, `raster_to_vector_polygons` | both |

## The DEM source: USGS 3DEP 1/3 arc-second, verified live

- **Source.** The official bulk staged products on The National Map's S3 bucket:
  `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/<tile>/USGS_13_<tile>.tif`
- **Tiles.** Each is a 1°×1° Cloud-Optimised GeoTIFF: LZW compression, 512×512 blocks,
  Float32, NAD83 (EPSG:4269), 10,812×10,812 px at 1/3″ (about 10 m), nodata −999999.
- **Coverage.** The Adirondacks bbox in `regions.yml` (−75.40, 43.00, −73.30, 44.90) is
  exactly six tiles:

  | Tile | Size | Last modified |
  |---|---|---|
  | n44w074 | 481 MB | 2026-04-01 |
  | n44w075 | 448 MB | 2026-01-26 |
  | n44w076 | 450 MB | 2026-03-18 |
  | n45w074 | 432 MB | 2026-04-01 |
  | n45w075 | 451 MB | 2026-01-26 |
  | n45w076 | 320 MB | 2026-03-18 |

  All six returned HTTP 200 on 2026-10-23 and downloaded in about 1 min. The TNM Access
  API (`tnmaccess.nationalmap.gov/api/v1/products`) lists the same tiles with publication
  dates. Those dates are what the pipeline uses to tell whether the source has changed.

**Fallbacks, both also verified live.**

- The 3DEP ImageServer `exportImage`. A 300×300 Float32 GeoTIFF straight in EPSG:5070
  took 2.7 s. This is the same service our getSamples elevation already uses.
- AWS Terrain Tiles (Terrarium PNG), which the map already uses for hillshade.

Terrarium is quantised to 1/256 m and resampled from mixed sources, so it is the last
resort.

**Working grid.** Everything is warped with GDAL (`gdalwarp`, already a dependency through
GeoDjango) to EPSG:5070, `METRIC_SRID`. Tools then measure in metres, and results line up
with `geom_m`.

## Measurements

The test areas were:

- A 3 km box centred on Marcy Dam (EPSG:5070 1742160, 2554943), at 10 m (300² = 90 k
  cells) and at 30 m (100²).
- A 15 km box around it at 10 m (1,500² = 2.25 M cells), to see how cost scales.

The setup:

- One process per tool, with a cached compiled module.
- Each tool runs single-threaded. WASI preview 1 has no threads; parallelism comes from
  running tiles in separate processes.
- The machine is an 8-core Apple Silicon laptop with 8 GB RAM.
- "MB" is the WASM linear memory after the run. That memory only grows, so it is the
  tool's peak.

The region estimates assume cost grows linearly with cells:

- At 10 m the region bbox is 21,150 × 24,435 = 517 M cells.
- At 30 m it is 7,050 × 8,145 = 57 M cells.

The 30 m estimate uses the per-cell cost measured at 10 m. For the neighbourhood tools,
whose window is a fixed number of metres and therefore 3× fewer cells at 30 m, that is an
upper bound.

| Tool | 3 km @10 m | 3 km @30 m | 15 km @10 m | Region @10 m est. (CPU-h) | Region @30 m est. (CPU-min) |
|---|---|---|---|---|---|
| `slope` | 0.04 s / 10 MB | 0.02 s / 8 MB | 1.25 s / 85 MB | 0.1 | 0.5 |
| `aspect` | 0.05 s / 10 MB | 0.01 s / 8 MB | 1.18 s / 85 MB | 0.1 | 0.5 |
| `breach_depressions_least_cost` | 0.03 s / 13 MB | 0.01 s / 10 MB | 0.89 s / 134 MB | 0.1 | 0.4 |
| `fill_depressions` | 0.03 s / 12 MB | 0.01 s / 9 MB | 0.85 s / 117 MB | 0.1 | 0.4 |
| `depth_in_sink` | 0.01 s / 14 MB | 0.01 s / 10 MB | 0.27 s / 134 MB | <0.1 | 0.1 |
| `d8_flow_accum` | 0.03 s / 11 MB | 0.01 s / 9 MB | 0.74 s / 85 MB | <0.1 | 0.3 |
| `dinf_flow_accum` | 0.05 s / 12 MB | 0.01 s / 9 MB | 1.40 s / 128 MB | 0.1 | 0.6 |
| `fd8_flow_accum` | 0.05 s / 11 MB | 0.01 s / 9 MB | 1.27 s / 112 MB | 0.1 | 0.5 |
| `wetness_index` | 0.02 s / 11 MB | 0.01 s / 8 MB | 0.70 s / 93 MB | <0.1 | 0.3 |
| `relative_topographic_position` (600 m window) | 3.11 s / 10 MB | 0.05 s / 8 MB | 85.8 s / 82 MB | 5.5 | 36.5 |
| `deviation_from_mean_elevation` (600 m window) | 0.02 s / 10 MB | 0.01 s / 8 MB | 0.70 s / 93 MB | <0.1 | 0.3 |
| `openness` (500 m) | 0.48 s / 11 MB | 0.03 s / 8 MB | 12.6 s / 94 MB | 0.8 | 5.3 |
| `geomorphons` (500 m) | 0.40 s / 9 MB | 0.02 s / 8 MB | 11.4 s / 49 MB | 0.7 | 4.8 |
| `exposure_towards_wind_flux` (270°, 1 km) | 0.19 s / 10 MB | 0.01 s / 8 MB | 5.59 s / 93 MB | 0.4 | 2.4 |
| `sky_view_factor` (1 km) | 6.94 s / 11 MB | 0.28 s / 8 MB | 209 s / 105 MB | 13.3 | 88.9 |
| `viewshed` (1 station, whole box) | 0.26 s / 10 MB | 0.02 s / 8 MB | 4.42 s / 65 MB | n/a (per site) | n/a |
| `visibility_index` (2 km) | 2.44 s / 10 MB | 0.04 s / 8 MB | **> 18 min, stopped** | impractical | impractical |
| `solar_radiation` (Jun–Aug, 15-day step) | 1.84 s / 26 MB | 0.14 s / 10 MB | 52.0 s / 461 MB | 3.3 | 22.1 |
| `reclass` | – | – | 0.42 s / 79 MB | <0.1 | 0.2 |
| `raster_to_vector_polygons` | 0.13 s / 20 MB | – | 11.3 s / 328 MB | 0.7 | 4.8 |

Cost scales linearly: 25× the cells cost 25–31× the time for the per-cell tools.

### Per-site viewshed

These are single stations at Marcy Dam, with a 1.7 m eye height and the window cut
around the site:

| Resolution | Radius | Cells | Run time | Visible area |
|---|---|---|---|---|
| 30 m | 10 km | 444 k | 0.27 s | 7.7 km² |
| 20 m | 8 km | 640 k | 0.66 s | 7.6 km² |
| 10 m | 5 km | 1.0 M | 2.70 s | 6.0 km² |

### Whole-region hydrology in one piece

Flow accumulation is only right if each cell sees its whole upslope area, so it has to
run over the region in one piece, not in tiles.

| Resolution | Cells | Result |
|---|---|---|
| 30 m | 57.4 M | **Fails.** Reading the GeoTIFF runs out of WASM memory before any tool starts. |
| 60 m | 14.4 M | `breach_depressions_least_cost` **panics** after 173 s at 2.4 GB (`capacity overflow`). |
| 45 m | 25.5 M | `breach_depressions_least_cost` panics the same way, after 309 s at 2.6 GB. |
| 45 m | 25.5 M | **Works.** `fill_depressions` 10.6 s / 1.2 GB, then `dinf_flow_accum` 14.6 s / 1.3 GB, then `wetness_index` 6.5 s / 0.9 GB. `slope` takes 11.9 s / 0.8 GB. |

The memory ceiling, in a size sweep with `slope`:

| Cells | Result |
|---|---|
| 3,000² | 4.7 s / 312 MB |
| 4,000² | 8.2 s / 573 MB |
| 5,000² | 13.2 s / 982 MB |
| 6,000² | **fails** writing the output, at 1.2 GB |

## Limits

- **Memory ceiling: about 25 M cells per call.** wasm32 caps linear memory at 4 GiB, and
  Rust on wasm32 can't make one allocation over 2 GiB. A `Vec` that doubles past that
  panics with `capacity overflow`, which is how breach-depressions failed at 45 m and
  60 m. In practice, a call is safe up to about 5,000² cells (≈1 GB). Anything bigger is
  processed in tiles.
- **Single-threaded per call.** Throughput comes from running tiles and sites in parallel
  processes.
- **Breaching doesn't scale.** `breach_depressions_least_cost` fails at region scale, so
  region hydrology uses priority-flood `fill_depressions`, which is O(n log n) and lean.
  Filling flattens a depression into a lake surface, which over-states contributing area
  slightly in big flats. That is acceptable for a wet/dry index.
- **Inputs are copied.** Each call copies its inputs into a temporary `/work` on local
  disk, and outputs come back as Python `bytes`. Tiles must fit on disk twice and in
  Python memory once.
- **Neighbourhood tools need overlap.** Any tool that reads a window (DEV, openness,
  viewshed, depressions) needs tile overlap of at least its radius, or values are wrong
  near tile edges.
- **`visibility_index` and `sky_view_factor` are too slow** for the whole region at
  campsite resolution.
- **Bare earth.** 3DEP is a bare-earth DEM: trees, buildings and recent changes (beaver
  ponds, blowdown) aren't in it. A viewshed is "what the terrain would let you see", and
  forest will block much of it. The app must say so.
- **A point can sit on the wrong cell.** The Marcy Dam campsite point falls on the
  brook's flow line (TWI 24, the box maximum). Per-site facts should sample a small
  neighbourhood (TM05-141 uses the median within 15 m), not one cell.

## Resolutions chosen, and why

| Output | Tools | Resolution | Area | Why |
|---|---|---|---|---|
| Drainage index (TWI) and pooling-risk zones | `fill_depressions` → `dinf_flow_accum --out_type=sca` → `slope` → `wetness_index` | **45 m** | **Whole region, one piece** | Contributing area needs the whole catchment. 45 m is the finest grid that fits a single call (25.5 M cells, 1.3 GB peak, 32 s). 30 m can't be read. |
| Local pooling (puddles, hollows) | `depth_in_sink --zero_background=true` | **10 m** | Tiles of ≤4,000² cells with 1 km overlap | Campsite-scale hollows are tens of metres across, too small to see at 45 m. A depression's depth only needs the depression itself, so tiling with overlap is safe. About 1 CPU-min for the region. |
| Aspect / sun | `aspect` | **10 m** | Tiles, 1 cell of overlap is enough (100 m used) | Tent-pad scale, matching the 10 m slope stencil (TM05-64). 0.1 CPU-h. |
| Shelter / exposure, and exposed zones | `deviation_from_mean_elevation`, 1 km window (33 cells) | **30 m** | Tiles with 1 km overlap | DEV is the standardised height above the surrounding terrain: positive is a ridge or knob, negative a hollow. It is explainable in one sentence and takes 0.3 CPU-min for the region. `relative_topographic_position` gives the same signal 100× slower. `openness` and `geomorphons` are Sprint 8 options. |
| Viewshed: visible area, main direction, water view | `viewshed --height=1.7`, one station per site | **30 m, 10 km radius** | A window per site | 0.27 s per site, so about 7 CPU-min for 1,500 sites. Visible area matches 20 m to 1% and costs 2.5× less. 10 m only affords a 5 km radius, which cuts off distant summits. |
| Zone polygons | `reclass` → `raster_to_vector_polygons`, then PostGIS simplify | Same as the source raster (45 m, 30 m) | | At 10 m, a 15 km box polygonises to a 30 MB GeoJSON. Coarse classes with a minimum area keep the zones small enough to tile. |

**Estimated full run, sequential:**

- about 32 s of hydrology
- about 2 CPU-min of 10 m tiles
- under 1 CPU-min of DEV
- about 7 CPU-min of viewsheds
- plus GDAL warping and the database writes

That is roughly 15 minutes on one core. The pipeline (TM05-141) measures the real figure.

### Not chosen now

These are Sprint 8 candidates; none needs a new dependency:

- `solar_radiation`: summer Wh/m². TM05-162 uses `time_in_daylight` for sun hours
  instead (see [Sun hours](#sun-hours-tm05-162)).
- `exposure_towards_wind_flux`: wind exposure to the prevailing westerlies. TM05-148 uses
  `fetch_analysis` instead (see [Wind exposure](#wind-exposure-tm05-148)).
- `geomorphons`: landform classes such as ridge, hollow or valley.
- `openness`.
- `sky_view_factor` at 30 m, as a cold-air-pooling helper. TM05-147 uses
  `elevation_percentile` instead (see [Cold-air pooling](#cold-air-pooling-tm05-147)).

## Disk and caching

None of this is committed:

- **Source tiles.** 2.58 GB (2.4 GiB), in `~/.cache/campsite/terrain/3dep-13/`. Re-downloaded only
  when TNM's publication date changes.
- **Region mosaics.**
  - 45 m hydrology grid: 73 MB compressed.
  - 30 m grid: 161 MB compressed.
  - The 10 m "mosaic" is a GDAL VRT over the six tiles. Each 10 m tile is warped from it
    on demand, so the 2 GB 10 m raster never sits on disk.
- **Database.** Only derived answers go in: per-site facts and simplified zone polygons,
  with a provenance record, as CLAUDE.md requires for raster sources.

## The pipeline (TM05-141)

```
make terrain REGION=adirondacks            # or: manage.py terrain adirondacks
manage.py terrain adirondacks --only wetness,viewshed --workers 4
manage.py terrain adirondacks --fresh      # recompute every tile
```

`make data` and `make refresh` run it as their last step, after enrichment.

The code is in `backend/terrain/`:

| Module | Does |
|---|---|
| `tools.yml` | The registry: runtime pin, DEM source, grids, per-region values (`regional`), tools, and classification thresholds |
| `registry.py` | Loads and validates `tools.yml`. A typo fails at load, naming the tool. |
| `runtime.py` | Runs a GeoLibre tool in-process (wasmtime). Checks the runtime's sha256, caches the compiled module, and reports each call's peak memory. |
| `dem.py` | 3DEP source tiles (downloaded once, re-fetched when Last-Modified changes), the region VRT and mosaics, and grid tiles cut with GDAL warp |
| `grid.py` | Tiling: cores that partition the region, plus overlap |
| `worker.py` | One tool on one tile, or the viewshed for a batch of sites (in worker processes) |
| `mappers.py` | Sampling facts around a site, and the classes and reasons the app shows |
| `pipeline.py` | The run: tasks, storage, resume, zone merge, classification, provenance |
| `models.py` | `TerrainRun`, `TerrainFacts`, `TerrainZone`, `TerrainTile` |

### What a run does

1. **Prepare.**
   - Check the runtime against `runtime.sha256`, fetching it on first use.
   - HEAD each 3DEP tile for the region. Download any that are missing or changed.
   - Build the region VRT and each untiled or zone-making grid's mosaic. The mosaics are
     named by the source digest, so they are rebuilt only when a source tile changes.
2. **Tiles.** For every tool, the grid is cut into tiles: cores that partition the
   region, each padded by `overlap_m` on every side. A worker process:
   1. warps the padded DEM tile
   2. runs the tool's chain of GeoLibre steps
   3. samples each fact for the campsites whose point is in the core (median, max or
      circular mean within `radius_m`)
   4. reclassifies and polygonises the zone classes inside the core, in pieces of at most
      2,500² cells

   Grids marked `sites_only` skip tiles with no campsite in their core.
3. **Per-site tools.** The viewshed runs on a 30 m window of `radius_m` around each site,
   in batches of 50. It records the visible area, the compass sector with the most visible
   ground beyond 200 m, and the visible outline.
4. **Merge zones.** Each layer's tile pieces are unioned per class, simplified
   (`simplify_m`), and anything under `min_area_m2` is dropped. The merged polygons are
   what `/api/tiles/pooling-risk/…` and `/api/tiles/exposure/…` serve.
5. **Classify.** Each site's values become the app's classes:
   - pooling risk, from sink depth and the wetness index (the higher wins)
   - facing and sun, from aspect, or "flat" under 4°
   - shelter, from DEV
   - cold-air pooling, from the elevation percentile (TM05-147)
   - wind exposure, from the upwind distance to rising ground (TM05-148)
   - sun hours and morning sun, from the share of daytime in direct sun (TM05-162)
   - water view: at least 5,000 m² of NHD lake or pond inside the viewshed

**Idempotent and resumable.**

- Each finished tile is a `TerrainTile` row, keyed by the config digest and the DEM
  digest. A re-run skips those tiles.
- Facts are merged per campsite, and zone pieces are replaced per tile.
- An interrupted run therefore resumes where it stopped. A finished run, run again, only
  re-merges and re-classifies.
- Changing `tools.yml` or a source tile changes a digest, so the affected work is redone.

**Only derived results are stored.** Rasters exist only in worker memory and GeoLibre's
temporary `/work`. The database gets numbers and classes per site, polygons, and a
`TerrainRun` that records:

- geolibre-wasm, runtime and wasmtime versions, and the runtime's sha256
- the DEM tiles, with URLs, Last-Modified and sizes
- `tools.yml` as run
- per-tool CPU time, task counts and peak WASM memory
- campsite coverage per fact
- zone counts per layer and class
- the peak RSS of the run

### Adding a terrain tool

A tool is one entry under `tools:`. For example, terrain roughness at 30 m as a per-site
fact:

```yaml
  roughness:
    grid: coarse                       # hydrology (45 m, whole region), coarse (30 m) or fine (10 m)
    steps:                             # GeoLibre calls in order; {dem} or {<earlier step id>}
      - {id: tri, tool: ruggedness_index, args: {input: "{dem}"}}
    facts:                             # sampled into TerrainFacts.values
      roughness: {sample: median, radius_m: 30}
```

That is the whole change: the value appears in `TerrainFacts.values["roughness"]` for
every campsite on the next run. To also draw it as a map layer, add `zones`:

```yaml
    zones:
      layer: rough-ground              # the vector tile layer name
      classes:                         # ascending; a cell takes the highest class it reaches
        - {class: high, min: 2.5}
      min_area_m2: 50000
      simplify_m: 30
```

Then add a `TileLayer` for `rough-ground` in `backend/api/tiles.py`, like `exposure`.

**Class ranges (TM05-153).** A class covers `min` (inclusive) up to `max` (exclusive):

- Without `max`, a class runs up to the next class's `min`, or without limit.
- Without `min`, it runs down without limit. Only the first class can leave it out. This
  is for a zone *below* a value, for example `{class: sheltered, max: -0.75}`.
- Classes go in ascending order and can't overlap.
- A cell in no class is in no zone.

**Zones only the potential-campsite search reads (TM05-153).** Two tools write layers that
aren't served as tiles or used by scoring. They exist so a computed spot, which has no
site facts, can be ranked on the same ground classes a campsite gets
(docs/candidates.md, step 4):

| Tool | Grid | Layer (class) | Range |
|---|---|---|---|
| `shelter` | coarse, DEV as for `position` | `sheltered` (`sheltered`) | DEV below −0.75, a site's "sheltered" |
| `damp` | hydrology, TWI as for `wetness` | `damp-ground` (`medium`) | TWI 10 to 12.5, a site's medium pooling band |

Each recomputes its tool's chain rather than sharing it, because a tool writes one zone
layer. That costs one more DEV pass (about 1 min CPU) and one more whole-region hydrology
pass (about 1.5 min). TM05-147 (cold-air pooling, the `cold_air` tool) and TM05-148 (wind
exposure, the `wind` tool) plug into the same ranking by writing layers named `cold-air`
and `wind-exposure` (`backend/planning/candidates.yml`).

A new **class** shown in the app (like `pooling` or `shelter`) needs one small function in
`mappers.py`, plus a column on `TerrainFacts` if scoring or filtering reads it. A new
sampling method or per-site mapper is added to `SAMPLE_METHODS` or `MAPPERS` in
`registry.py`.

A grid's `overlap_m` must be at least the widest neighbourhood any of its tools reads.
`tests/test_terrain.py::test_tiling_with_overlap_has_no_seams` shows what happens
otherwise.

### Cold-air pooling (TM05-147)

On clear, calm nights the ground cools the air touching it. That air is denser than the
air above it, so it drains downhill and settles in the lowest ground around. A site in a
hollow or on a valley floor can be several degrees colder than a bench 30 m above it, with
more frost and heavier dew. The `cold_air` tool says where.

**The tool.** `elevation_percentile` on the 30 m `coarse` grid, over a 33 × 33-cell (about
1 km) window, the same window as `position`. Each cell gets the share (0–100%) of the
ground in the window that is lower than it: 0 is the lowest cell around, 50 a mid-slope,
100 a summit. Each site samples the median within 30 m, as `elev_percentile`.

| Class | `elev_percentile` | The panel says |
|---|---|---|
| `high` | below 10 | "In the lowest ground around: higher than only 4% of the land within about 1 km, where cold air settles on clear, calm nights." |
| `medium` | 10 to 25 | "Low-lying: 84% of the land within about 1 km is higher, so some cold air drains down to here on calm nights." |
| `low` | 25 and up | "Cold air drains away: 60% of the land within about 1 km is lower." |

- **The thresholds** are `classify.cold_air` (`high_below`, `medium_below`), and the
  `cold-air` zone layer uses the same values. A test keeps the map and the panel in
  agreement.
- **The zones.** `high` and `medium` are polygonised, at least 2 ha each and simplified
  to 30 m. `/api/tiles/cold-air/…` serves them, and the potential-campsite ranking reads
  the layer by its name (`planning/candidates.yml`, `cold_air`).
- **Why this tool.**
  - It is one number that explains itself ("lower than 96% of the ground around").
  - It is scale-free: a 20 m hollow on a plateau and a valley floor 300 m down both rank
    low. Cold air drains to whatever is lowest nearby.
  - It is cheap. On a synthetic 30 m DEM it took 2.5 s per million cells with 35 MB of
    WASM memory (geolibre-wasm 1.7.1, WSL on a Windows laptop), so about 4 CPU-minutes
    for the region's nine 30 m tiles.
  - `relative_topographic_position` gives a similar signal about 100× slower (see
    [Measurements](#measurements)).
  - `sky_view_factor` measures enclosure, not lowness, and is too slow at region scale.
  - `depth_in_sink` sees only closed depressions, not open valley floors, which are where
    most Adirondack cold-air pools form.
- **The 1 km window** fits the `coarse` grid's 1,500 m tile overlap, so tiling adds no
  seams (`test_tiling_with_overlap_has_no_seams`).
- **What it leaves out.**
  - Cold air only pools on calm, clear nights. Wind or cloud mixes it away, and the
    model doesn't know the weather.
  - A valley that is open downhill drains some of its cold air on down. The percentile
    can't tell a closed frost hollow from an open valley floor at the same rank, which is
    why `high` means the lowest tenth.
  - Bare earth: forest cover, which slows the drainage, isn't counted.
  - The thresholds are first estimates, not yet tuned against a full region run.

### Wind exposure (TM05-148)

The `shelter` class says whether a site stands above or below the ground around it, in
any direction. Wind exposure asks something narrower: is the ground upwind of the
site, towards the direction the wind usually comes from, open, or does a ridge or valley
wall break that wind?

**The tool.** `fetch_analysis` on its own 90 m `wind` grid. For each cell it searches
upwind, towards `wind_from_deg`, for the first ground that rises against the wind by more
than `hgt_inc` (5%, about 3°) above the cell. The result is the distance to that ground in
metres, the *fetch*. A negative value means nothing rose before the DEM ended, and gives
the distance searched. Each site samples the median within 90 m, as `wind_fetch_m`.

| Class | `wind_fetch_m` | The panel says |
|---|---|---|
| `sheltered` | 0 to 300 m | "Ground rises against a west wind about 120 m upwind, breaking it before it reaches here." |
| `moderate` | 300 m to 1 km | "Partly open to a west wind: the nearest ground rising against it is about 640 m upwind." |
| `exposed` | 1 km and up, or nothing rising within at least 1 km | "Open to a west wind: about 2.5 km of open ground upwind." |

- **The thresholds** are `classify.wind` (`sheltered_within_m`, `exposed_from_m`). The
  `wind-exposure` zone layer uses the same values. It holds `moderate` and `exposed`, the
  two classes the potential-campsite ranking reads (`planning/candidates.yml`, `wind`).
  Sheltered ground isn't zoned.
- **Seams.** Tiles overlap by 1,500 m, more than the 1 km at which ground counts as
  exposed. So a core cell's class is the same whichever tile computes it, even though the
  raw fetch past 1.5 km depends on the tile.
- **The region's edge.** There, the search stops short. A site whose search reached
  less than 1 km with nothing rising is *unknown*, not exposed. The zones count any
  negative value as exposed, so a strip along the region's upwind edge can be over-stated
  on the map.
- **Why 90 m.** On flat ground, such as a big lake, `fetch_analysis` walks to the tile
  edge from every cell, so its cost grows with the cube of the tile width.
  - Measured on synthetic DEMs: 49 s for 1,000² flat cells, 21 s for 1,000² rugged cells
    (25 MB of WASM memory).
  - At the 30 m grid's 3,000-cell tiles, the flat case would take about 25 minutes a tile.
  - At 90 m, a 1,000-cell tile (90 km) stays near a minute even when flat. Wind shelter is
    a landscape-scale effect, so 90 m loses little.
- **Why not `exposure_towards_wind_flux`.** On test planes, its horizon component behaved
  as documented: a 200 m wall 600 m upwind gave +0.30 rad. But its surface-angle
  component gave a north-facing slope a positive "exposure" to a north wind and a
  crosswind plane a non-zero value. We couldn't explain its sign, so it isn't used.

**The prevailing wind, per region.** `regional.wind_from_deg` in `tools.yml` is the
compass bearing the wind blows **from**, the convention `fetch_analysis` uses. That was
checked: a wall to the west is found at `azimuth: 270`. A region not listed uses
`default`. `Registry.for_region()` fills the value into the tool's `{wind_from_deg}`
argument for the region being run.

- Each site stores the direction it was classified for (`TerrainFacts.wind_from_deg`).
  The panel shows it with the class: "Estimate, assuming the prevailing wind is from the
  west (270°)".
- Changing a direction changes the registry digest, so the next run recomputes its tiles.

**The Adirondacks: 270°, from the west.**

- **Source:** ten years (2016–2025) of hourly 10 m wind from the
  [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
  (ERA5 reanalysis), the same provider as the app's forecasts. Four points were sampled
  across the park, with calm hours (under 1 m/s) left out.
- **Evidence:** the script and its output are in `artifacts/terrain/wind/`
  (`wind_rose.py`, `adirondacks-wind-rose.json`).

| Point | Most frequent sector (share of windy hours) | Resultant wind, from |
|---|---|---|
| Marcy Dam (High Peaks) | W, 27.5% (then S 19.4%, SW 18.7%) | 249° |
| Lake Placid | W, 28.3% (then SW 25.7%) | 241° |
| Newcomb (central) | NW, 31.7% (then W 21.4%) | 282° |
| Old Forge (southwest) | W, 20.6% (then S 19.8%, SW 19.3%) | 234° |
| **All four** | **W, 24.5%** (27.9% weighted by speed) | |

- West is the most frequent sector overall and at three of the four points, and it is
  also the strongest.
- The resultant runs from 234° to 282° between points, which brackets 270°. The valleys
  steer surface wind locally, which no single direction captures.
- `white-mountains-nh` and any other region use the `default` (270°) until someone gives
  them their own.

**What it leaves out.**

- One prevailing direction: a storm from the southeast, or a calm night, isn't the
  prevailing wind.
- Bare earth: forest breaks most wind at ground level, and the model doesn't see it.
- Funnelling along valleys and speed-up over ridges aren't modelled. Only whether
  terrain stands in the wind's way upwind is.
- The thresholds are first estimates, not yet tuned against a full region run.

### Sun hours (TM05-162)

The `sun` class (from aspect) says which way the ground faces. It doesn't say whether a
ridge across the valley hides the sun. Sun hours ask that directly: on a summer day, how
many hours is the site in direct sun, and does the sun reach it in the morning, early
enough to dry a tent and warm a cold camp?

**The tools.** Two entries, `sun` and `sun_morning`, both run `time_in_daylight`. For
each cell it finds the horizon in every direction, then follows the sun's path through
each day of the season. The result is the share (0 to 1) of daytime the cell is in direct
sun rather than in terrain shadow.

- `sun` runs from sunrise to sunset, and each site samples the median within 90 m as
  `sun_share`.
- `sun_morning` runs from sunrise to 10:00, sampled the same way as `morning_sun_share`.

**The assumptions.**

| | Value | Why |
|---|---|---|
| Season | 1 June (day 152) to 31 August (day 243), every day | The main backcountry camping season. `classify.sun_hours.season` names it in the panel, and a test keeps the days and the label equal. |
| Sun position | Each tile's own latitude and longitude, read from the DEM | Checked: on an EPSG:5070 tile it gives exactly what an explicit `latitude`/`longitude` gives. |
| Clock | `regional.summer_utc_offset`, UTC−04:00 (EDT) | "10:00" means 10 am on a camper's watch. Left out, the tool guesses UTC−05:00 from longitude, which moved the window an hour later: one test site went from 0.61 to 0.68 lit. |
| Morning | Sunrise to 10:00 | By 10 am a site in the sun has dried and warmed. One that is still shaded hasn't. |
| Horizon | Out to 5 km, sampled every 10° of azimuth | The sun is blocked by ridges kilometres away. 5 km covers a 1,000 m wall at 11°, and 10° bins halve the cost against the default 5°. |
| Grid | `sun`: 90 m, 1,000-cell tiles with 5 km overlap, campsite tiles only | The overlap has to cover the horizon search (a test checks it). Sun is a landscape-scale effect, so 90 m loses little. |

**Hours, classes and the panel.** Hours are `sun_share` times the mean day length over the
season at the site's latitude (`mappers.day_length_h`, sunrise to sunset at −0.833°). That
day length is 14.8 h at Marcy Dam, against an almanac's 15 h 29 min on Lake Placid's
longest day. A test checks it.

| Level | Direct sun on a June–August day | The panel says |
|---|---|---|
| `full` | 12 h or more | "About 14 h of direct sun on a day in June to August, out of about 15 h of daylight." |
| `partial` | 8 to 12 h | "About 10 h of direct sun on a day in June to August: the terrain shades it for about 5 of the 15 h of daylight." |
| `low` | under 8 h | "Only about 6 h of direct sun on a day in June to August: the terrain shades it for most of the 15 h of daylight." |

- **Morning sun** is `yes` when `morning_sun_share` is at least 0.5, meaning the site is
  in direct sun for most of sunrise to 10 am. The panel adds "In direct sun for most of
  the time from sunrise to 10 am", or "Higher ground shades it for most of…".
- **The Terrain section** shows "Sun hours: About 10 h of direct sun · no morning sun",
  with the reasons, and the label "Bare-earth estimate: shade from trees isn't counted".
- **Unknowns.** Each half is unknown on its own: a site with no `sun_share` still shows
  its morning sun.
- **Thresholds** are `classify.sun_hours` (`full_from_h`, `partial_from_h`,
  `morning_from_share`). They are first estimates, not yet tuned against a full region
  run. Nothing is zoned, so no tile layer is added.

**Measured** (geolibre-wasm 1.7.1, WSL on a Windows laptop):

- **Behaviour on synthetic 30 m DEMs**, one test site, June to August, in EDT. Flat ground
  is 0.99 lit all day and 0.98 in the morning: the tool trims a few minutes at sunrise.

  | Terrain | All day | Sunrise to 10:00 | Why |
  |---|---|---|---|
  | Flat | 0.99 | 0.98 | Lit all day |
  | 300 m wall 150 m to the south | 0.95 | 0.98 | The summer sun clears it |
  | 300 m wall 150 m to the north | 0.77 | 0.61 | The sun rises and sets in the north-east and north-west in summer |
  | 300 m ridge 150 m to the east | 0.63 | **0.00** | No morning sun |
  | 300 m ridge 150 m to the west | 0.63 | 0.98 | Evening shade only |

- **Cost.** On a full `sun` tile (1,111² cells with its overlap, rolling synthetic
  terrain), `sun` took 94 s and `sun_morning` 23 s, with at most 59 MB of WASM memory. The
  region's 90 m grid is at most nine tiles, so this is about 18 CPU-minutes, spread over
  the workers.

**Why `time_in_daylight`.**

- It answers the question directly: the share of time in direct sun, which turns into
  hours in one step.
- It reads latitude and longitude from the DEM, so each tile gets its own sun.
- `solar_radiation` gives Wh/m² (direct plus diffuse). Turning that into hours needs a
  clear-sky model, and it would mix slope steepness with shade.
- `horizon_angle` is one azimuth per call: 36 calls, then our own sun-path code.
- `shadow_image` is one moment in time.

**What it leaves out.**

- Trees. Under a closed canopy, most of the "direct sun" here never reaches the ground.
  The label says so.
- Clouds: these are clear-sky hours.
- Shade from terrain beyond 5 km. That is rare at Adirondack relief.
- A site's own slope. A cell's horizon includes the ground around it, but the facing
  (`sun`) is the 10 m answer for that.

### Measured: the Adirondacks (2026-10-23)

These figures are from a full `--fresh` run on 3 workers (8-core laptop), with the DEM
already cached. Logs are in `artifacts/terrain/pipeline/` (run-fresh-tiles.txt, run-resume-merge-classify.txt).

| Step | Tasks | CPU time | Peak WASM memory |
|---|---|---|---|
| `wetness` (45 m, whole region: fill, D∞, slope, TWI, plus zones) | 1 | 93 s | 1,267 MB |
| `sink` (10 m) | 35 tiles | 233 s | 578 MB |
| `slope` (10 m) | 35 tiles | 346 s | 350 MB |
| `aspect` (10 m) | 35 tiles | 297 s | 349 MB |
| `position` (30 m DEV, plus zones) | 9 tiles | 56 s | 373 MB |
| `viewshed` (30 m, 10 km, per site) | 15 batches of 50 | 689 s | 26 MB |
| **All tiles** | 130 | 1,714 s | **603 s wall** |
| Zone merge (both layers) | | | 40 s |
| Classify (incl. the water-view intersections) | | | 56 s |

**Totals and outputs.**

- **Total:** about 12 minutes for a fresh run once the DEM is cached. The one-time setup
  adds the 2.6 GB download (about 1 min) and the mosaics (about 1.5 min).
- **Re-runs:** a finished run, run again, reuses all 130 tasks and takes 98 s, which is
  the merge plus classify.
- **Peak memory:** about 1.3 GB, the hydrology worker. The others stay under 600 MB.
- **Coverage** of the region's 743 campsites:
  - pooling, shelter, facing and viewshed: 742 each (99.9%)
  - aspect direction: 726 (97.7%; the rest are flat)
  - wetness index: 737 (99.2%)
  - The one site with nothing, Iroquois Municipal Campground, falls on nodata. Its
    viewshed failed with "no station points intersect valid DEM cells", which a run
    records in `counts.failed_sites`, and the run carries on.
- **Classes:**
  - pooling: 55 high, 265 medium, 422 low
  - shelter: 22 exposed, 533 moderate, 187 sheltered
  - water in view (1 ha or more within 2 km): 535 (72%). Most Adirondack lean-tos face
    a pond or lake.
- **Zones:** 16,676 pooling-risk polygons and 18,715 exposure polygons, each at least 5 ha
  (2 ha for pooling), simplified.

**Judgment calls** made while running it on real data:

- **A hollow alone is only medium pooling risk.** Sink depths under campsites ran to
  metres (90th percentile 1.4 m), which is DEM artefacts: culverts under road
  embankments, and flattened ponds. High now needs water draining in as well
  (`sink_high_needs_twi`).
- **"Sheltered" means DEV below −0.75**, about a quarter of sites. At −0.5 it was half of
  them, because campsites sit mostly in valleys.
- **Water view counts lakes within 2 km only.** Over the whole 10 km viewshed, bare
  earth "sees" some lake from 77% of sites.
- **Zones aren't unioned across tiles.** See `merge_zones` for why. The fills draw
  seamlessly.
- **GDAL cuts are written to real temporary files, not /vsimem/.** Blocks left unwritten
  there read as zeros in GeoLibre, which gave plateaus at 0 m and made
  `fill_depressions` run for 10+ minutes instead of 11 s.

### Measured: the White Mountains (2026-11-10, TM05-163)

`make terrain REGION=white-mountains-nh`, a first run from an empty cache, on 3 workers
(Apple Silicon laptop), against a database restored from `dev-data-2026-11-08`. The log is
in `artifacts/terrain/pipeline/white-mountains-nh-run-2026-11-10.txt`.

**The mosaic** is built from the configured source, `dem` in `tools.yml`: the four 3DEP
1/3 arc-second tiles covering the `regions.yml` bbox `[-72.00, 43.85, -70.95, 44.55]`,
which are `n44w071`, `n44w072`, `n45w071` and `n45w072` (1.7 GB). Their URLs and
Last-Modified dates are in the run's `TerrainRun.dem_source`.

**Regional values.** The White Mountains have no entry in `regional`, so they run on the
defaults: wind from the west (270°) and Eastern Daylight Time. Mount Washington's
prevailing wind is commonly given as westerly to northwesterly, so 270° is a fair first
value, but it has not been checked against reanalysis data the way the Adirondacks one was. Giving
the region its own direction later, from a wind rose like the Adirondacks one, is a config
change, but it changes the registry digest and so recomputes every region's tiles.

| Step | Tasks | CPU time | Peak WASM memory |
|---|---|---|---|
| `wetness` (45 m, whole region) | 1 | 13.8 s | 258 MB |
| `sink` (10 m) | 10 tiles | 37.9 s | 566 MB |
| `slope` (10 m) | 10 tiles | 75.0 s | 349 MB |
| `aspect` (10 m) | 10 tiles | 72.9 s | 348 MB |
| `position` (30 m DEV) | 4 tiles | 7.8 s | 362 MB |
| `shelter` | 4 tiles | 9.8 s | 362 MB |
| `damp` | 1 | 17.7 s | 359 MB |
| `cold_air` (TM05-147) | 4 tiles | 28.0 s | 241 MB |
| `wind` (TM05-148) | 4 tiles | 12.6 s | 142 MB |
| `sun`, `sun_morning` (TM05-162) | 2 + 2 tiles | 86.5 s | 53 MB |
| `viewshed` (30 m, per site) | 16 batches | 779.4 s | 20 MB |
| **All tiles** | 68 | 1,141 s | about 400 s wall |
| Zone merge (all layers) | | | 15.0 s |
| Classify | | | 55.8 s |

**Runtime.**

- **Pipeline:** 1,204 s (20 min). Of that, 730 s is the one-time prepare: downloading the
  four tiles and building the mosaics. A re-run reuses all 68 tasks.
- **End to end,** `make terrain` took 1,445 s (24 min) wall clock, measured with
  `/usr/bin/time -l`.

**Peak memory.** The run's peak RSS was 984 MB (`TerrainRun.peak_rss_mb`; `/usr/bin/time`
agrees, at 1,032 MB maximum resident set size). The largest single GeoLibre call was the
10 m `sink` tile, at 566 MB of WASM memory. The whole-region hydrology grid is smaller
than in the Adirondacks (258 MB against 1,267 MB) because the region is about a fifth of
the area.

**Coverage** of the region's 756 campsites:

- every fact (pooling, shelter, facing, cold air, wind, sun hours, morning sun, viewshed,
  and the raw values under them): 756 each (100%), with no failed sites
- water in view (1 ha or more within 2 km): 180 (23.8%). That is much lower than the
  Adirondacks' 72%, which fits a region with far fewer lakes and ponds (NHD rivers don't
  count toward a water view).

**Classes.**

- pooling: 33 high, 152 medium, 571 low
- shelter: 3 exposed, 600 moderate, 153 sheltered
- cold air: 4 high, 109 medium, 643 low
- wind: 309 exposed, 148 moderate, 299 sheltered
- sun hours: 699 full, 57 partial; morning sun at 755 of 756
- facing: 429 flat (under 4°), the rest mostly south, east, southwest and west

**Zones:** 2,318 pooling-risk, 2,711 exposure, 2,209 sheltered, 4,969 damp-ground, 6,147
cold-air (1,513 high, 4,634 medium) and 4,213 wind-exposure (1,573 exposed, 2,640
moderate) polygons. The tile endpoint (`/api/tiles/<layer>/{z}/{x}/{y}.mvt`) serves the
White Mountains pooling-risk, exposure, cold-air and wind-exposure layers. Two tiles were
checked, over the Presidential Range and the Pemigewasset.

**The Adirondacks are unchanged.** A hash of all 743 Adirondacks `TerrainFacts` rows (the
values and every class), and the count and area of each zone layer, were identical before
and after the White Mountains run. Facts and zones are stored per region, and the registry
digest did not change.
