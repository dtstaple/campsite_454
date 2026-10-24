"""
The terrain pipeline (TM05-141): every registered tool over a region, then the facts and
zones they produce. `manage.py terrain <region>` (and `make terrain`) runs it.

1. **Prepare.** Check the GeoLibre runtime. Make sure the 3DEP source tiles are current.
   Build (or reuse) the region's mosaics.
2. **Run each tiled tool tile by tile**, in worker processes. A worker cuts its DEM tile
   (core plus overlap), runs the tool's GeoLibre chain, samples the facts for campsites
   in the core, and polygonises the zone classes inside the core. The parent writes those
   and records the tile as finished. A re-run skips finished tiles under the same config
   and DEM, so an interrupted run resumes.
3. **Run per-site tools** (the viewshed) in batches of sites, resumable the same way.
4. **Merge** each zone layer's tile pieces into simplified polygons.
5. **Classify** every site's facts into the classes the app shows, and work out the
   water view.

Workers never touch the database; they return plain data. Rasters live only in worker
memory and GeoLibre's temporary /work: nothing raster-shaped is stored.
"""

from __future__ import annotations

import json
import multiprocessing
import resource
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.db import connection, transaction
from django.utils import timezone

from geodata.models import Campsite
from pipeline.regions import get_region
from terrain import dem, mappers, runtime, worker
from terrain.grid import contains, layout
from terrain.models import TerrainFacts, TerrainRun, TerrainTile, TerrainZone
from terrain.registry import Registry, Tool

#: Sites per resumable batch for per-site tools.
SITE_BATCH = 50


# --- parent side -------------------------------------------------------------------


@dataclass
class Stats:
    seconds: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    tiles: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    skipped: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    peak_mb: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    #: Sites a per-site tool could not run for, with the tool's message.
    failed: dict[int, str] = field(default_factory=dict)


def _site_points(bbox, srid) -> list[tuple[int, float, float]]:
    box = Polygon.from_bbox(bbox)
    box.srid = 4326
    rows = Campsite.objects.filter(geom__intersects=box).order_by("id").values_list("id", "geom_m")
    return [(site_id, point.x, point.y) for site_id, point in rows]


def _merge_values(run: TerrainRun, facts: dict[int, dict]) -> None:
    now = timezone.now()
    existing = TerrainFacts.objects.in_bulk(list(facts))
    create, update = [], []
    for site_id, values in facts.items():
        row = existing.get(site_id)
        if row is None:
            create.append(
                TerrainFacts(campsite_id=site_id, run=run, computed_at=now, values=values)
            )
        else:
            row.values = {**row.values, **values}
            row.run, row.computed_at = run, now
            update.append(row)
    TerrainFacts.objects.bulk_create(create)
    TerrainFacts.objects.bulk_update(update, ["values", "run", "computed_at"])


def _store_tile(run: TerrainRun, registry: Registry, region: str, result: dict, stats: Stats):
    tool = registry.tools[result["tool"]]
    with transaction.atomic():
        if result.get("facts"):
            _merge_values(run, result["facts"])
        if tool.zones:
            TerrainZone.objects.filter(
                region=region, layer=tool.zones.layer, tile=result["tile"]
            ).delete()
            TerrainZone.objects.bulk_create(
                [
                    TerrainZone(
                        region=region,
                        layer=tool.zones.layer,
                        zone_class=name,
                        tile=result["tile"],
                        run=run,
                        area_m2=0.0,
                        geom=_multipolygon(geometry),
                    )
                    for name, geometry in result["zones"]
                ]
            )
        if "sites" in result:
            _store_views(run, result["sites"])
        TerrainTile.objects.update_or_create(
            region=region,
            tool=tool.id,
            tile=result["tile"],
            config_digest=run.config_digest,
            dem_digest=run.dem_digest,
            defaults={
                "run": run,
                "seconds": result["seconds"],
                "peak_memory_mb": result["peak_mb"],
                "finished_at": timezone.now(),
            },
        )
    stats.failed.update(result.get("failed", {}))
    stats.seconds[tool.id] += result["seconds"]
    stats.tiles[tool.id] += 1
    stats.peak_mb[tool.id] = max(stats.peak_mb[tool.id], result["peak_mb"])


def _multipolygon(geometry: dict) -> MultiPolygon:
    geom = GEOSGeometry(json.dumps(geometry), srid=4326)
    if geom.geom_type == "Polygon":
        geom = MultiPolygon(geom, srid=4326)
    return geom


VIEWSHED_SIMPLIFY_M = 15


def _store_views(run: TerrainRun, sites: dict[int, dict]) -> None:
    now = timezone.now()
    for site_id, view in sites.items():
        shape = None
        if view["polygons"]:
            parts = [_multipolygon(g) for g in view["polygons"]]
            merged = MultiPolygon([p for part in parts for p in part], srid=4326).unary_union
            merged.transform(5070)
            merged = merged.simplify(VIEWSHED_SIMPLIFY_M, preserve_topology=True)
            merged.transform(4326)
            if merged.geom_type == "Polygon":
                merged = MultiPolygon(merged, srid=4326)
            shape = merged if merged.geom_type == "MultiPolygon" and not merged.empty else None
        row, _ = TerrainFacts.objects.get_or_create(
            campsite_id=site_id, defaults={"run": run, "computed_at": now}
        )
        row.values = {**row.values, "view_area_km2": round(view["area_km2"], 3)}
        row.view_area_km2 = round(view["area_km2"], 3)
        row.view_direction = view["direction"]
        row.viewshed = shape
        row.run, row.computed_at = run, now
        row.save()


MERGE_SQL = """
    WITH simple AS (
        SELECT zone_class,
               ST_MakeValid(ST_SimplifyPreserveTopology(geom_m, %(simplify)s)) AS geom
        FROM terrain_terrainzone
        WHERE region = %(region)s AND layer = %(layer)s AND tile <> ''
    )
    INSERT INTO terrain_terrainzone (region, layer, zone_class, tile, run_id, area_m2, geom)
    SELECT %(region)s, %(layer)s, zone_class, '', %(run)s, ST_Area(geom),
           ST_Multi(ST_Transform(geom, 4326))
    FROM (SELECT zone_class, (ST_Dump(geom)).geom AS geom FROM simple) parts
    WHERE ST_GeometryType(geom) = 'ST_Polygon' AND ST_Area(geom) >= %(min_area)s
"""


def merge_zones(run: TerrainRun, region: str, tool: Tool) -> dict[str, int]:
    """Replace a layer's served zones with its tile pieces, simplified, dropping those
    under `min_area_m2`.

    Pieces are neither unioned nor clustered. Pooling-risk zones follow the drainage
    network into a few region-sized dendritic shapes, and both a union and an
    ST_ClusterDBSCAN over them ran past 10 minutes. Tiles draw adjacent fills
    seamlessly, and a piece is cut only where a tile or polygonising chunk ends
    (75-112 km apart). So the only cost is that a zone straddling such an edge is
    measured in two parts against `min_area_m2`."""
    zones = tool.zones
    with transaction.atomic():
        TerrainZone.objects.filter(region=region, layer=zones.layer, tile="").delete()
        with connection.cursor() as cursor:
            cursor.execute(
                MERGE_SQL,
                {
                    "region": region,
                    "layer": zones.layer,
                    "simplify": zones.simplify_m,
                    "min_area": zones.min_area_m2,
                    "run": run.id,
                },
            )
    merged = TerrainZone.objects.filter(region=region, layer=zones.layer, tile="")
    return {c.name: merged.filter(zone_class=c.name).count() for c in zones.classes}


WATER_VIEW_SQL = """
    SELECT COALESCE(SUM(ST_Area(ST_Intersection(w.geom_m, f.near_view))), 0)
    FROM (
        SELECT c.geom_m AS site,
               ST_Intersection(ST_Transform(t.viewshed, 5070), ST_Buffer(c.geom_m, %(within)s))
                   AS near_view
        FROM terrain_terrainfacts t JOIN geodata_campsite c ON c.id = t.campsite_id
        WHERE t.campsite_id = %(site)s
    ) f
    JOIN geodata_waterfeature w
      ON w.feature_type = 'lake'
     AND ST_DWithin(w.geom_m, f.site, %(within)s)
     AND ST_Intersects(w.geom_m, f.near_view)
"""


def classify(registry: Registry, site_ids: list[int]) -> None:
    """The classes the app shows, from each site's sampled values."""
    cfg = registry.classify
    rows = TerrainFacts.objects.filter(campsite_id__in=site_ids)
    for row in rows.iterator():
        row.pooling, row.pooling_reason = mappers.pooling(row.values, cfg["pooling"])
        row.facing, row.sun = mappers.sun(row.values, cfg["sun"])
        row.shelter, row.shelter_reason = mappers.shelter(row.values, cfg["shelter"])
        if row.viewshed is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    WATER_VIEW_SQL,
                    {"site": row.campsite_id, "within": cfg["view"]["water_within_m"]},
                )
                area = cursor.fetchone()[0] or 0.0
            row.water_view_m2 = round(area, 1)
            row.water_view = area >= cfg["view"]["water_min_m2"]
        row.save()


def run(
    region: str,
    registry: Registry,
    *,
    only: list[str] | None = None,
    workers: int = 3,
    fresh: bool = False,
    log=print,
) -> TerrainRun:
    started = time.perf_counter()
    aoi = get_region(region)
    srid, nodata = int(registry.dem["srid"]), float(registry.dem["nodata"])
    tools = [t for name, t in registry.tools.items() if not only or name in only]

    log("Preparing the runtime and DEM")
    wasm = runtime.runtime_path(registry.runtime)
    runtime.prepare(wasm)
    source = dem.fetch(region, aoi.bbox, registry.dem["tile_url"], log=log)
    vrt = dem.build_vrt(source)
    region_m = dem.region_bounds_m(aoi.bbox, srid)
    sites = _site_points(aoi.bbox, srid)

    import geolibre_wasm

    record = TerrainRun.objects.create(
        region=region,
        started_at=timezone.now(),
        config_digest=registry.digest,
        dem_digest=source.digest,
        tool_versions={
            "geolibre_wasm": geolibre_wasm.__version__,
            "runtime": registry.runtime["version"],
            "runtime_sha256": registry.runtime["sha256"],
            "wasmtime": runtime.WASMTIME_VERSION,
            "tools": {t.id: t.geolibre_tools for t in tools},
        },
        dem_source={"name": registry.dem["name"], **source.provenance(registry.dem["tile_url"])},
        config=registry.raw,
    )
    if fresh:
        TerrainTile.objects.filter(region=region, tool__in=[t.id for t in tools]).delete()
    done = set(
        TerrainTile.objects.filter(
            region=region, config_digest=registry.digest, dem_digest=source.digest
        ).values_list("tool", "tile")
    )

    sources: dict[str, tuple[Path, bool]] = {}
    for tool in tools:
        grid = tool.grid
        if grid.name in sources:
            continue
        if grid.sites_only:
            sources[grid.name] = (vrt, False)  # averaged down per tile from the source
        else:
            path = dem.mosaic(vrt, source, region_m, grid.resolution_m, srid, nodata, log=log)
            sources[grid.name] = (path, True)
    prepare_s = time.perf_counter() - started

    tasks = []
    stats = Stats()
    for tool in tools:
        src, same_grid = sources[tool.grid.name]
        if tool.per_site:
            for index in range(0, len(sites), SITE_BATCH):
                key = f"s{index // SITE_BATCH}"
                if (tool.id, key) in done:
                    stats.skipped[tool.id] += 1
                    continue
                tasks.append(
                    (
                        "sites",
                        {
                            "tool": tool,
                            "key": key,
                            "sites": sites[index : index + SITE_BATCH],
                            "src": str(src),
                            "srid": srid,
                            "nodata": nodata,
                            "wasm": str(wasm),
                            "view_cfg": registry.classify["view"],
                        },
                    )
                )
            continue
        grid = tool.grid
        for tile in layout(region_m, grid.resolution_m, grid.tile_cells, grid.overlap_m):
            in_core = [s for s in sites if contains(tile.core, s[1], s[2])]
            if grid.sites_only and not in_core:
                continue
            if (tool.id, tile.key) in done:
                stats.skipped[tool.id] += 1
                continue
            tasks.append(
                (
                    "tile",
                    {
                        "tool": tool,
                        "tile": tile,
                        "sites": in_core,
                        "src": str(src),
                        "same_grid": same_grid,
                        "srid": srid,
                        "nodata": nodata,
                        "wasm": str(wasm),
                    },
                )
            )

    log(
        f"{len(tasks)} tasks for {len(tools)} tools on {workers} workers "
        f"({sum(stats.skipped.values())} already done)"
    )

    def store(count: int, result: dict) -> None:
        _store_tile(record, registry, region, result, stats)
        log(
            f"  [{count}/{len(tasks)}] {result['tool']} {result['tile']}: "
            f"{result['seconds']:.1f} s, {result['peak_mb']:.0f} MB"
        )

    if workers <= 0:
        # In-process, for tests and debugging.
        for count, task in enumerate(tasks, start=1):
            store(count, worker.dispatch(task))
    else:
        context = multiprocessing.get_context("spawn")
        with context.Pool(workers, initializer=worker.init, maxtasksperchild=8) as pool:
            # Stored as they finish, so one slow tile (the whole-region hydrology) holds
            # nothing else up, and an interruption loses only the tiles in flight.
            for count, result in enumerate(pool.imap_unordered(worker.dispatch, tasks), start=1):
                store(count, result)

    counts: dict = {"sites": len(sites), "zones": {}, "failed_sites": stats.failed}
    merge_started = time.perf_counter()
    for tool in tools:
        if tool.zones:
            counts["zones"][tool.zones.layer] = merge_zones(record, region, tool)
    merge_s = time.perf_counter() - merge_started

    classify_started = time.perf_counter()
    site_ids = [s[0] for s in sites]
    classify(registry, site_ids)
    classify_s = time.perf_counter() - classify_started

    facts = TerrainFacts.objects.filter(campsite_id__in=site_ids)
    names = [f.name for t in registry.tools.values() for f in t.facts if f.sample]
    counts["coverage"] = {
        **{n: facts.filter(values__has_key=n).count() for n in names},
        "pooling": facts.exclude(pooling="").count(),
        "facing": facts.exclude(facing="").count(),
        "shelter": facts.exclude(shelter="").count(),
        "viewshed": facts.exclude(viewshed=None).count(),
        "water_view": facts.filter(water_view=True).count(),
    }
    children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    own = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    scale = 1 if sys.platform == "darwin" else 1024  # macOS reports bytes, Linux KiB
    record.peak_rss_mb = round(max(children, own) * scale / 2**20, 1)
    record.timings = {
        "total_s": round(time.perf_counter() - started, 1),
        "prepare_s": round(prepare_s, 1),
        "merge_zones_s": round(merge_s, 1),
        "classify_s": round(classify_s, 1),
        "workers": workers,
        "tools": {
            t.id: {
                "cpu_s": round(stats.seconds[t.id], 1),
                "tasks": stats.tiles[t.id],
                "skipped": stats.skipped[t.id],
                "peak_wasm_mb": round(stats.peak_mb[t.id]),
            }
            for t in tools
        },
    }
    record.counts = counts
    record.finished_at = timezone.now()
    record.save()
    return record
