/**
 * Client for the map data API. Contract: docs/api.md
 *
 * Three things here exist for speed rather than correctness, and all three depend on
 * the API returning a *deterministic* sample for a given bounding box:
 *
 *   - one request per viewport instead of three, via /api/map-data/
 *   - the bounding box is snapped outward to a grid, so a small pan produces the same
 *     request rather than a new one
 *   - responses are cached by that snapped key, so panning back is instant
 */

import type { Feature } from "geojson";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export type LayerName = "campsites" | "trails" | "water";

export interface Metadata {
  layer: LayerName;
  returned: number;
  matched: number;
  truncated: boolean;
  limit: number;
  simplify: number | null;
}

export interface FeatureCollection {
  type: "FeatureCollection";
  bbox: [number, number, number, number];
  features: Feature[];
  metadata: Metadata;
}

export interface MapData {
  bbox: [number, number, number, number];
  layers: Partial<Record<LayerName, FeatureCollection>>;
  metadata: { truncated: boolean; returned: number; limit: number; simplify: number | null };
}

export type Bbox = [number, number, number, number];

/**
 * Zoom to simplification tolerance, from the table in docs/api.md.
 * Returns null at close zoom, where the doc says to omit the parameter.
 */
export function simplifyForZoom(zoom: number): number | null {
  if (zoom >= 14) return null;
  if (zoom >= 11) return 0.0001;
  if (zoom >= 9) return 0.0005;
  return 0.001;
}

/**
 * Below this zoom an individual stream or trail is well under a pixel wide, so the
 * request is skipped entirely rather than made and discarded. Campsites are points and
 * stay meaningful at any zoom, and there are few enough that they cost nothing.
 */
export const MIN_ZOOM_FOR_LINEWORK = 9;

export function layerVisibleAtZoom(layer: LayerName, zoom: number): boolean {
  if (layer === "campsites") return true;
  return zoom >= MIN_ZOOM_FOR_LINEWORK;
}

/**
 * Clamp a viewport bbox into the range the API accepts.
 *
 * map.getBounds() can return longitudes beyond +/-180 when the viewport is wider than
 * the world or has been panned across the antimeridian, and the API rejects those with
 * a 400.
 */
export function clampBbox([west, south, east, north]: Bbox): Bbox {
  const lon = (value: number) => Math.min(180, Math.max(-180, value));
  const lat = (value: number) => Math.min(90, Math.max(-90, value));
  return [lon(west), lat(south), lon(east), lat(north)];
}

/**
 * Expand a bbox outward onto a grid whose step is a quarter of the viewport span.
 *
 * Two things fall out of this. Small pans and nudges land on the same grid cell, so they
 * produce a byte-identical request that the cache already holds. And the slight
 * over-fetch means the edges of the viewport are already loaded when the user drags.
 */
export function snapBbox(bbox: Bbox): Bbox {
  const [west, south, east, north] = clampBbox(bbox);
  const step = Math.max((east - west) / 4, (north - south) / 4, 0.002);
  const down = (value: number) => Math.floor(value / step) * step;
  const up = (value: number) => Math.ceil(value / step) * step;
  const round = (value: number) => Number(value.toFixed(6));
  return clampBbox([round(down(west)), round(down(south)), round(up(east)), round(up(north))]);
}

export class ApiError extends Error {}

/** Cache of whole map-data responses, keyed by the snapped request. */
const CACHE_LIMIT = 40;
const cache = new Map<string, MapData>();

export function cacheStats() {
  return { size: cache.size, limit: CACHE_LIMIT };
}

export function clearCache() {
  cache.clear();
}

function remember(key: string, value: MapData) {
  cache.delete(key);
  cache.set(key, value);
  // Map preserves insertion order, so the first key is the least recently used.
  while (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
}

export interface MapDataResult {
  data: MapData;
  cached: boolean;
  bbox: Bbox;
}

/**
 * Every layer for one viewport, in a single request.
 *
 * Returns `cached: true` without touching the network when this exact snapped bbox and
 * simplification have been fetched before.
 */
export async function fetchMapData(
  bbox: Bbox,
  simplify: number | null,
  layers: LayerName[],
  signal?: AbortSignal,
): Promise<MapDataResult> {
  const snapped = snapBbox(bbox);
  const params = new URLSearchParams({ bbox: snapped.join(",") });
  if (simplify !== null) params.set("simplify", String(simplify));
  // Ask only for what will actually be drawn. Zoomed out past the linework
  // threshold this is the difference between 138 kB and 223 bytes.
  params.set("layers", [...layers].sort().join(","));

  const key = params.toString();
  const hit = cache.get(key);
  if (hit) {
    remember(key, hit); // refresh recency
    return { data: hit, cached: true, bbox: snapped };
  }

  const url = `${API_BASE_URL}/api/map-data/?${params}`;
  let response: Response;
  try {
    response = await fetch(url, { signal });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ApiError(`Could not reach the API at ${API_BASE_URL}. Is the backend running?`);
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body?.error) detail = body.error;
    } catch {
      /* non-JSON error body; keep the status */
    }
    throw new ApiError(detail);
  }

  const data = (await response.json()) as MapData;
  remember(key, data);
  return { data, cached: false, bbox: snapped };
}
