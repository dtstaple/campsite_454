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

- `solar_radiation`: summer Wh/m², which could become "sun hours" (22 CPU-min at 30 m).
- `exposure_towards_wind_flux`: wind exposure to the prevailing westerlies.
- `geomorphons`: landform classes such as ridge, hollow or valley.
- `openness`.
- `sky_view_factor` at 30 m, as a cold-air-pooling helper.

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
