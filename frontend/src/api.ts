/**
 * Thin client for the map data API. Contract: docs/api.md
 *
 * Prototype only -- enough to prove the render path works end to end.
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
 * Clamp a viewport bbox into the range the API accepts.
 *
 * map.getBounds() can return longitudes beyond +/-180 when the viewport is wider
 * than the world or has been panned across the antimeridian, and the API rejects
 * those with a 400. Clamping here keeps a harmless pan from surfacing as an error.
 */
export function clampBbox([west, south, east, north]: Bbox): Bbox {
  const lon = (value: number) => Math.min(180, Math.max(-180, value));
  const lat = (value: number) => Math.min(90, Math.max(-90, value));
  return [lon(west), lat(south), lon(east), lat(north)];
}

export class ApiError extends Error {}

export async function fetchLayer(
  layer: LayerName,
  bbox: Bbox,
  simplify: number | null,
  signal?: AbortSignal,
): Promise<FeatureCollection> {
  const params = new URLSearchParams({ bbox: clampBbox(bbox).join(",") });
  if (simplify !== null) params.set("simplify", String(simplify));

  const url = `${API_BASE_URL}/api/${layer}/?${params}`;
  let response: Response;
  try {
    response = await fetch(url, { signal });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ApiError(
      `Could not reach the API at ${API_BASE_URL}. Is the backend running?`,
    );
  }

  if (!response.ok) {
    // The API returns {"error": "..."} with a readable reason on 400.
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body?.error) detail = body.error;
    } catch {
      /* non-JSON error body; keep the status */
    }
    throw new ApiError(`${layer}: ${detail}`);
  }

  return (await response.json()) as FeatureCollection;
}
