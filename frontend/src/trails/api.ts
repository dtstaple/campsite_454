/**
 * Client for the named-route endpoints (TM05-60). Contract: docs/api.md, "Named routes".
 */

import type { FeatureCollection, LineString, MultiLineString } from "geojson";
import { API_BASE_URL, type Bbox } from "../api";

export interface RouteSummary {
  osm_id: number;
  name: string;
  ref: string | null;
  network: string | null;
  operator: string | null;
  length_m: number;
}

export interface ProfileStats {
  length_m: number;
  gain_m: number;
  loss_m: number;
  high_m: number;
  high_at_m: number;
  low_m: number;
  low_at_m: number;
  start_m: number;
  end_m: number;
  max_grade_pct: number;
  max_grade_at_m: number;
  naive_gain_m: number;
  naive_loss_m: number;
}

export type Profile =
  | {
      status: "ok";
      reason: null;
      stats: ProfileStats;
      distance_m: number[];
      elevation_m: number[];
      source: { name: string; datasets: string[]; resolution_m: number[]; cached: boolean };
    }
  | { status: "unavailable"; reason: string };

/** Only the parts of the contract-1 score the panel reads; see docs/scoring.md. */
export interface ScoreSummary {
  score: number;
  model_version: string;
  caps: { factor: string; max_score: number; reason: string }[];
}

export interface CampsiteAlong {
  id: string;
  source: string;
  name: string | null;
  site_type: string;
  lon: number;
  lat: number;
  distance_along_m: number;
  distance_from_route_m: number;
  score: number | null;
  score_breakdown: ScoreSummary;
}

export interface RouteDetail extends RouteSummary {
  source_id: string;
  geometry: MultiLineString;
  /** The route as one ordered path; every "distance along" is measured on this. */
  line: LineString & { length_m: number };
  path: { parts: number; parts_used: number; parts_left_out: number; left_out_m: number };
  profile: Profile;
  campsites: { within_m: number; count: number; truncated: boolean; items: CampsiteAlong[] };
}

export class RouteApiError extends Error {}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { signal });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new RouteApiError(`Could not reach the API at ${API_BASE_URL}.`);
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body?.error) detail = body.error;
    } catch {
      /* non-JSON error body; keep the status */
    }
    throw new RouteApiError(detail);
  }
  return (await response.json()) as T;
}

/** Named routes in a viewport, simplified for drawing. */
export function fetchRoutes(bbox: Bbox, signal?: AbortSignal) {
  const params = new URLSearchParams({ bbox: bbox.join(","), simplify: "0.0001" });
  return getJson<FeatureCollection<MultiLineString, RouteSummary>>(
    `${API_BASE_URL}/api/routes/?${params}`,
    signal,
  );
}

/** One route in detail. The first request for a route can take seconds (profile). */
export function fetchRouteDetail(osmId: number, withinM: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ campsites_within_m: String(withinM) });
  return getJson<RouteDetail>(`${API_BASE_URL}/api/routes/${osmId}/?${params}`, signal);
}
