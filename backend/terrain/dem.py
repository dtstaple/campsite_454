"""
The DEM: USGS 3DEP 1/3 arc-second tiles, a region mosaic, and grid tiles (TM05-141).

Everything here lives in the cache directory (runtime.cache_dir(), outside git):

    3dep-13/USGS_13_<tile>.tif     the source tiles, 1x1 degree COGs from The National Map
    3dep-13/signature.json         each tile's Last-Modified and size when downloaded
    mosaic/<region>-<sig>.vrt      the source tiles as one virtual raster (no copy)
    mosaic/<region>-<res>m-<sig>.tif   a whole-region grid, for grids that are cropped often

`<sig>` is a hash of the source tiles' signatures. A mosaic is rebuilt only when a source
tile changes, which a HEAD request detects.

Grid tiles are cut with GDAL's warp, through GeoDjango. That means no GDAL command-line
tools and no numpy: averaging when downsampling the 10 m source, and nearest-neighbour
when cropping a mosaic already at the grid's resolution.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from django.contrib.gis.gdal import GDALRaster
from django.contrib.gis.geos import MultiPoint, Point

from terrain.grid import Bounds, align, cells
from terrain.runtime import cache_dir

FLOAT32 = 6  # GDAL's GDT_Float32


def source_tiles(bbox: tuple[float, float, float, float]) -> list[str]:
    """The 3DEP 1x1 degree tile names covering a WGS84 bbox. Tile nYYwXXX spans
    latitude YY-1..YY and longitude -XXX..-XXX+1."""
    west, south, east, north = bbox
    names = []
    for lat in range(math.floor(south) + 1, math.ceil(north) + 1):
        for lon in range(math.ceil(-west), math.ceil(-east) - 1, -1):
            names.append(f"n{lat:02d}w{lon:03d}")
    return names


def region_bounds_m(bbox: tuple[float, float, float, float], srid: int) -> Bounds:
    """The region bbox as an envelope in the working CRS. The edges are sampled at 21
    points each, so the envelope still contains them after they curve in projection."""
    west, south, east, north = bbox
    steps = [i / 20 for i in range(21)]
    edge = (
        [Point(west + (east - west) * t, south) for t in steps]
        + [Point(west + (east - west) * t, north) for t in steps]
        + [Point(west, south + (north - south) * t) for t in steps]
        + [Point(east, south + (north - south) * t) for t in steps]
    )
    points = MultiPoint(edge, srid=4326)
    points.transform(srid)
    return points.extent


@dataclass
class Source:
    """The downloaded source tiles for one region."""

    region: str
    names: list[str]
    directory: Path
    signatures: dict[str, dict]

    @property
    def digest(self) -> str:
        canonical = json.dumps({n: self.signatures[n] for n in self.names}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]

    def provenance(self, url_template: str) -> dict:
        return {
            "tiles": {
                n: {"url": url_template.format(tile=n), **self.signatures[n]} for n in self.names
            },
            "digest": self.digest,
        }


def _head(url: str) -> dict:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "campsite"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return {
            "last_modified": response.headers.get("Last-Modified", ""),
            "bytes": int(response.headers.get("Content-Length", 0)),
        }


def _download(url: str, path: Path) -> None:
    partial = path.with_suffix(".part")
    request = urllib.request.Request(url, headers={"User-Agent": "campsite"})
    with urllib.request.urlopen(request, timeout=600) as response, partial.open("wb") as out:  # noqa: S310
        while chunk := response.read(1 << 20):
            out.write(chunk)
    partial.replace(path)


def fetch(region: str, bbox, url_template: str, log=print) -> Source:
    """Make sure every source tile for `bbox` is downloaded and current.

    A tile is downloaded when it is missing or its Last-Modified or size changed. When
    the service can't be reached, the tiles already on disk are used, with a warning.
    """
    directory = cache_dir() / "3dep-13"
    directory.mkdir(parents=True, exist_ok=True)
    signature_file = directory / "signature.json"
    known = json.loads(signature_file.read_text()) if signature_file.exists() else {}
    names = source_tiles(bbox)
    for name in names:
        url = url_template.format(tile=name)
        path = directory / f"USGS_13_{name}.tif"
        try:
            remote = _head(url)
        except OSError as error:
            if path.exists() and name in known:
                log(f"  {name}: {error}; using the copy on disk")
                continue
            raise
        if not path.exists() or known.get(name) != remote:
            log(f"  {name}: downloading {remote['bytes'] / 2**20:.0f} MB")
            _download(url, path)
            known[name] = remote
            signature_file.write_text(json.dumps(known, indent=1, sort_keys=True))
    return Source(region, names, directory, {n: known[n] for n in names})


def build_vrt(source: Source) -> Path:
    """The source tiles as one GDAL virtual raster, written once per source digest."""
    out = cache_dir() / "mosaic" / f"{source.region}-{source.digest}.vrt"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    rasters = [GDALRaster(str(source.directory / f"USGS_13_{n}.tif")) for n in source.names]
    x_res, y_res = rasters[0].scale.x, rasters[0].scale.y
    west = min(r.origin.x for r in rasters)
    north = max(r.origin.y for r in rasters)
    east = max(r.origin.x + r.width * x_res for r in rasters)
    south = min(r.origin.y + r.height * y_res for r in rasters)
    width = round((east - west) / x_res)
    height = round((south - north) / y_res)
    nodata = rasters[0].bands[0].nodata_value
    sources = []
    for name, raster in zip(source.names, rasters, strict=True):
        x_off = round((raster.origin.x - west) / x_res)
        y_off = round((raster.origin.y - north) / y_res)
        path = escape(str(source.directory / f"USGS_13_{name}.tif"))
        sources.append(
            f"<ComplexSource><SourceFilename>{path}</SourceFilename><SourceBand>1</SourceBand>"
            f'<SrcRect xOff="0" yOff="0" xSize="{raster.width}" ySize="{raster.height}"/>'
            f'<DstRect xOff="{x_off}" yOff="{y_off}" '
            f'xSize="{raster.width}" ySize="{raster.height}"/>'
            f"<NODATA>{nodata}</NODATA></ComplexSource>"
        )
    srs = escape(rasters[0].srs.wkt)
    out.write_text(
        f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}">'
        f"<SRS>{srs}</SRS>"
        f"<GeoTransform>{west!r}, {x_res!r}, 0, {north!r}, 0, {y_res!r}</GeoTransform>"
        f'<VRTRasterBand dataType="Float32" band="1"><NoDataValue>{nodata}</NoDataValue>'
        + "".join(sources)
        + "</VRTRasterBand></VRTDataset>"
    )
    return out


def warp(
    src: GDALRaster,
    bounds: Bounds,
    resolution: float,
    srid: int,
    name: str,
    nodata: float,
    resampling: str = "Average",
) -> GDALRaster:
    """`bounds` (aligned) of `src` at `resolution` in `srid`, as a new raster `name`
    (a /vsimem/ path or a file)."""
    width, height = cells(bounds, resolution)
    return src.warp(
        {
            "name": name,
            "driver": "GTiff",
            "srid": srid,
            "origin": [bounds[0], bounds[3]],
            "width": width,
            "height": height,
            "scale": [resolution, -resolution],
            "resampling": resampling,
            "datatype": FLOAT32,
            "bands": [{"nodata_value": nodata}],
            # Tiled: GeoLibre's reader rejects GDAL's default one-row strips on large
            # rasters ("invalid dimensions").
            "papsz_options": {"tiled": "yes", "blockxsize": 256, "blockysize": 256},
        }
    )


def mosaic(
    vrt: Path,
    source: Source,
    region: Bounds,
    resolution: float,
    srid: int,
    nodata: float,
    log=print,
) -> Path:
    """The whole region at `resolution`, written once per source digest."""
    out = cache_dir() / "mosaic" / f"{source.region}-{int(resolution)}m-{source.digest}.tif"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        log(f"  building {out.name}")
        partial = out.with_suffix(".part.tif")
        raster = warp(
            GDALRaster(str(vrt)), align(region, resolution), resolution, srid, str(partial), nodata
        )
        del raster  # closes and flushes the file
        partial.replace(out)
    return out


def tile_bytes(
    src_path: Path,
    bounds: Bounds,
    resolution: float,
    srid: int,
    nodata: float,
    same_grid: bool,
    label: str,
) -> bytes:
    """One grid tile as GeoTIFF bytes, for GeoLibre's /work. Cropped (nearest) from a
    mosaic already on the grid, or averaged down from the source."""
    return warp_bytes(
        GDALRaster(str(src_path)),
        bounds,
        resolution,
        srid,
        nodata,
        "NearestNeighbour" if same_grid else "Average",
        label,
    )


def warp_bytes(
    src: GDALRaster,
    bounds: Bounds,
    resolution: float,
    srid: int,
    nodata: float,
    resampling: str,
    label: str,
) -> bytes:
    """`warp()` to GeoTIFF bytes, by way of a real temporary file.

    Not /vsimem/: warping there leaves blocks with no source data unwritten, and
    GeoLibre's TIFF reader takes a missing block as zeros. Outside the DEM's footprint
    that is a plateau at 0 m instead of nodata. That gives wrong values and makes
    fill_depressions grind through millions of flat cells (TM05-141). Written to disk,
    GDAL writes every block, nodata included.
    """
    with tempfile.TemporaryDirectory(prefix="terrain-tile-") as directory:
        path = Path(directory) / f"{label}.tif"
        raster = warp(src, bounds, resolution, srid, str(path), nodata, resampling=resampling)
        del raster  # closes and flushes the file
        return path.read_bytes()
