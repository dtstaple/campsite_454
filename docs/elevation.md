# Elevation profiles (TM05-59)

Every named route (TM05-58) can produce an elevation profile: the distance/elevation pairs a
chart draws, plus gain, loss, high and low points, and the steepest grade. It is the first
raster consumer of the analysis cache (TM05-44, docs/architecture.md). Elevation is sampled
on demand and only the derived profile is stored, never pixels.

Code: `backend/analysis/analyses/elevation.py` (`RouteProfile`). Run or inspect one with:

```
python manage.py route_profile "Van Hoevenberg Trail" --published-mi 7.4 --published-gain-ft 3166
```

## Source: USGS 3DEP, verified live

Verified on 2026-10-02 with real route geometry before any code depended on it:

```
POST https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/getSamples
     geometry={"points": [[lon, lat], ...], "spatialReference": {"wkid": 4326}}
     geometryType=esriGeometryMultipoint
     returnFirstValueOnly=true
     interpolation=RSP_BilinearInterpolation
     outFields=Name,VerticalDatum,AcquisitionDate
     f=json
→ 200
{"samples": [
   {"location": {"x": -73.9298, "y": 44.1269, "spatialReference": {"wkid": 4326}},
    "locationId": 17, "value": "1334.385375977", "resolution": 1, "rasterId": 116579,
    "attributes": {"Name": "NY_NH_Gaps_D24",
                   "VerticalDatum": "North American Vertical Datum of 1988 (NAVD 88)", ...}},
   ...]}
```

- A polyline request also worked, but placing the sample points ourselves (a multipoint) is
  what makes each sample's distance along the route exact.
- **Batch size.** All 455 points of the Van Hoevenberg Trail went in one POST, ~1 s. The
  code sends batches of 400 to stay well clear of any limit.
- **Ordering.** Samples come back out of order and are matched back by `locationId`.
- **Units and resolution.** Values are metres, NAVD 88. Over the High Peaks the service
  answered from two 1 m LiDAR collections (`2014_New_York_Clinton_Essex_Lake_Champlain_QL2_LiDAR`
  and `NY_NH_Gaps_D24`).
- **Missing data.** A `"NoData"` value is filled by linear interpolation and counted in
  provenance (`nodata_count`).

Because 3DEP worked, the AWS Terrarium fallback named in the story was not needed and is
not implemented. If 3DEP is down, the profile raises `AnalysisError` and nothing is
cached. Terrarium remains the documented fallback, with its encoding already verified for
the hillshade.

## Method

1. **Stitch** the route's members into one ordered line (`stitch`). Touching members are
   merged. The merged parts are then chained end to end from the longest, attaching any part
   whose end is within 50 m of the chain's start or end (reversed if needed). Parts that
   never attach — a parallel bypass whose ends meet the middle of the main line, or a
   disconnected stub — are **left out and counted** in `path`, never drawn as a straight
   jump. Van Hoevenberg: 2 merged parts, 1 used, 972 m left out (the Marcy Dam bypass).
2. **Sample** every 25 m along the line in EPSG:5070 metres, plus the end point.
3. **Fetch** elevations from 3DEP, fill NoData, and keep the raw series.
4. **Smooth** with a centred moving average over 100 m (5 samples).
5. **Gain and loss** with a 3 m threshold. A change is counted only once the smoothed
   elevation has moved 3 m from the last counted point. The naive sum of every positive step
   is kept alongside (`naive_gain_m`) for comparison.
6. **Max grade** over any stretch of at least 100 m horizontal, never between adjacent
   samples, so one noisy sample cannot produce a 60% "grade".

**Why 100 m and 3 m.** Both were chosen before calibrating, not fitted to the calibration
route. A 100 m window is about one switchback leg. 3 m is several times the vertical noise
of 1 m LiDAR on rocky trail, but well under any climb a hiker would notice.

## Stored value

```json
{
  "stats": {"length_m": 11373.0, "gain_m": 1007.4, "loss_m": 46.9,
            "high_m": 1627.6, "high_at_m": 11373.0, "low_m": 638.8, "low_at_m": 600.0,
            "start_m": 666.6, "end_m": 1627.6, "max_grade_pct": 33.0, "max_grade_at_m": 11125.0,
            "naive_gain_m": 1077.0, "naive_loss_m": 114.2},
  "distance_m": [0.0, 25.0, ...],
  "elevation_m": [666.0, 665.1, ...],
  "path": {"parts": 2, "parts_used": 1, "parts_left_out": 1, "left_out_m": 971.7,
           "largest_join_gap_m": 0.0},
  "line": [[-73.962732, 44.182899], ...],
  "params": {"spacing_m": 25, "smoothing_window_m": 100, "threshold_m": 3, "grade_window_m": 100}
}
```

- `elevation_m` is the raw (gap-filled) series; a chart may smooth it for display.
- `line` is the stitched path in WGS84, which the map and the 3D camera follow.
- Provenance adds `source: usgs-3dep`, the URL, `sample_count`, `nodata_count`, `datasets`,
  `vertical_datum` and `resolution_m`.
- **Cache key and TTL.** The cache key is the route geometry, so an unchanged route is never
  recomputed and a re-ingested route whose geometry changed gets a new profile. The TTL is
  one year, because terrain does not change.

## Calibration: Mount Marcy via the Van Hoevenberg Trail

Published: about **7.4 mi** and roughly **3,100+ ft** of gain one way, from Adirondak Loj to
the summit. For the gain error the reference used is **3,166 ft**, the commonly cited
figure. That is also just above the net rise implied by the published trailhead and summit
elevations (≈2,180 → 5,344 ft), which is the floor any true gain must clear.

| | Measured | Published | Error |
|---|---|---|---|
| Length (stitched main line) | 7.07 mi (11,373 m) | ~7.4 mi | **−4.5%** |
| Gain, smoothed + threshold | 3,305 ft | 3,166 ft | **+4.4%** |
| Gain, naive sum | 3,533 ft | 3,166 ft | +11.6% |
| Start / high point | 2,187 / 5,340 ft | ~2,180 / 5,344 ft | +7 / −4 ft |
| Loss | 154 ft | — | real dips (Phelps Brook) |
| Max grade | 33% at 6.91 mi | — | the summit cone |

- **Length runs 4.5% short.** OSM's main line is 7.07 mi. Trail signs and guidebooks round,
  often include the parking-lot approach, and the relation's 0.6 mi bypass is excluded by
  design.
- **Endpoints are within 7 ft** of the published trailhead and summit elevations, which says
  the 3DEP sampling itself is accurate. The gain error is mostly method, not data.
- **Smoothing and the threshold cut the overstatement from 11.6% to 4.4%.**

Sensitivity, from `route_profile` (gain in ft; no extra 3DEP calls):

| Window ↓ / threshold → | 0 m | 1 m | 3 m | 5 m | 10 m |
|---|---|---|---|---|---|
| 25 m (no smoothing) | 3,533 | 3,503 | 3,385 | 3,337 | 3,217 |
| 50 m | 3,395 | 3,363 | 3,326 | 3,318 | 3,202 |
| **100 m** | 3,355 | 3,332 | **3,305** | 3,295 | 3,210 |
| 200 m | 3,305 | 3,290 | 3,269 | 3,209 | 3,221 |
| 400 m | 3,202 | 3,192 | 3,188 | 3,173 | 3,159 |

Heavier settings get closer to 3,166 ft. They get there by flattening real climbs, and with
one calibration route that is curve-fitting, so the a-priori defaults stay. A second
calibration route (e.g. a White Mountains route with a published gain) is the right way to
revisit them.

## Cost

| Run | Time |
|---|---|
| First computation for Van Hoevenberg (11.4 km, 456 samples, 2 batches) | 3.8 s |
| — before batching the sample reprojection | 15.0 s |
| Cached read | 7.8 ms |

Most of the original 15 s was not 3DEP. Each sample point was reprojected on its own, and
building a GDAL transformation costs ~14 ms. Reprojecting all samples in one call cut the
computation to 3.8 s with identical results.

Profiles are therefore computed on first request and cached, rather than precomputed for all
452 routes. Precomputing would mean several thousand 3DEP requests at once.
