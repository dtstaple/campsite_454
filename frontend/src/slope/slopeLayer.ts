/**
 * The slope-angle layer (TM05-84): a raster source served by a custom MapLibre protocol,
 * "campsite-slope://z/x/y". Each tile is the Terrarium DEM tile the hillshade already uses
 * (layers.ts TERRAIN_TILES), turned into slope bands by a web worker (slope.worker.ts).
 * No new tile source and no server work.
 *
 * Band colours come from theme.css (--slope-*), read once when the protocol is registered.
 * Order: over the hillshade and satellite imagery, under the contours and every data layer.
 */

import * as maplibregl from "maplibre-gl";
import { TERRAIN_TILES } from "../map/layers";
import { CONTOUR_LINE_LAYER } from "../map/contours";
import { numericToken, token } from "../theme";
import { BANDS, parseColour, type Rgba } from "./slope";

export const SLOPE_SOURCE = "slope-angle";
export const SLOPE_LAYER = "slope-angle";
const PROTOCOL = "campsite-slope";

/** Slope is shaded from this zoom. A zoom-12 DEM (27 m pixels) finds only 64% of the
 * 30°+ terrain a zoom-14 one does; zoom 13 finds 87% (docs/terrain.md). */
export const SLOPE_MIN_ZOOM = 13;
/** Tiles are computed up to here and stretched beyond: the DEM has no finer detail. */
const SLOPE_MAX_ZOOM = 14;

/** Whether this browser can compute slope tiles at all. */
export function slopeSupported(): boolean {
  return typeof Worker !== "undefined" && typeof OffscreenCanvas !== "undefined";
}

export function slopePalette(): Rgba[] {
  return BANDS.map((band) => parseColour(token(band.token)));
}

let registered = false;

function register(): void {
  if (registered) return;
  registered = true;
  const worker = new Worker(new URL("./slope.worker.ts", import.meta.url), { type: "module" });
  const pending = new Map<number, { resolve: (b: ArrayBuffer) => void; reject: (e: Error) => void }>();
  let next = 0;
  worker.onmessage = (event: MessageEvent<{ id: number; buffer?: ArrayBuffer; error?: string }>) => {
    const entry = pending.get(event.data.id);
    if (!entry) return;
    pending.delete(event.data.id);
    if (event.data.buffer) entry.resolve(event.data.buffer);
    else entry.reject(new Error(event.data.error ?? "slope tile failed"));
  };
  const palette = slopePalette();

  maplibregl.addProtocol(PROTOCOL, (params, abort) => {
    const match = /(\d+)\/(\d+)\/(\d+)$/.exec(params.url);
    if (!match) return Promise.reject(new Error(`Bad slope tile URL ${params.url}`));
    const [z, x, y] = match.slice(1).map(Number);
    const url = TERRAIN_TILES.replace("{z}", String(z))
      .replace("{x}", String(x))
      .replace("{y}", String(y));
    const id = next++;
    return new Promise<{ data: ArrayBuffer }>((resolve, reject) => {
      pending.set(id, { resolve: (data) => resolve({ data }), reject });
      abort.signal.addEventListener("abort", () => {
        pending.delete(id);
        reject(new DOMException("Aborted", "AbortError"));
      });
      worker.postMessage({ id, url, z, y, palette });
    });
  });
}

function firstSymbolLayerId(map: maplibregl.Map): string | undefined {
  return map.getStyle().layers?.find((layer) => layer.type === "symbol")?.id;
}

/** Add the slope source and layer. Call once on `load`, after the contours. */
export function addSlopeLayer(map: maplibregl.Map, visible: boolean, opacity: number): void {
  if (!slopeSupported() || map.getSource(SLOPE_SOURCE)) return;
  register();
  map.addSource(SLOPE_SOURCE, {
    type: "raster",
    tiles: [`${PROTOCOL}://{z}/{x}/{y}`],
    tileSize: 256,
    minzoom: SLOPE_MIN_ZOOM,
    maxzoom: SLOPE_MAX_ZOOM,
    attribution: "Slope from Mapzen Terrain Tiles (USGS 3DEP)",
  });
  map.addLayer(
    {
      id: SLOPE_LAYER,
      type: "raster",
      source: SLOPE_SOURCE,
      minzoom: SLOPE_MIN_ZOOM,
      layout: { visibility: visible ? "visible" : "none" },
      paint: {
        "raster-opacity": opacity,
        "raster-resampling": "linear",
        "raster-fade-duration": 0,
      },
    },
    map.getLayer(CONTOUR_LINE_LAYER) ? CONTOUR_LINE_LAYER : firstSymbolLayerId(map),
  );
}

export function setSlopeVisible(map: maplibregl.Map, visible: boolean): void {
  if (map.getLayer(SLOPE_LAYER)) {
    map.setLayoutProperty(SLOPE_LAYER, "visibility", visible ? "visible" : "none");
  }
}

export function setSlopeOpacity(map: maplibregl.Map, opacity: number): void {
  if (map.getLayer(SLOPE_LAYER)) map.setPaintProperty(SLOPE_LAYER, "raster-opacity", opacity);
}

/** The opacity the layer starts at, from theme.css. */
export function defaultSlopeOpacity(): number {
  return numericToken("--slope-default-opacity", 0.55);
}
