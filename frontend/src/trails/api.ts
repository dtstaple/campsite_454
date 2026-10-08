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
  /** TM05-71: the detail panel's name, derived from nearby features when the source has none. */
  display_name?: string | null;
  display_name_derived?: boolean;
  site_type: string;
  lon: number;
  lat: number;
  distance_along_m: number;
  distance_from_route_m: number;
  /** TM05-73: past either end of the route there is no honest mile. Optional for older APIs. */
  position?: "along" | "near_start" | "near_end";
  position_label?: string | null;
  score: number | null;
  score_breakdown: ScoreSummary;
}

/** TM05-82: Shenandoah-rated difficulty, from the profile. Null when there is no profile. */
export interface Difficulty {
  rating: "easy" | "moderate" | "hard";
  label: string;
  shenandoah: number;
  formula: string;
  length_m: number;
  climb_m: number;
}

/** TM05-82: loop is measured; out & back and point to point are estimated from the ends. */
export interface RouteType {
  type: "loop" | "out_and_back" | "point_to_point";
  label: string;
  estimated: boolean;
  basis: { ends_apart_m: number; start?: string; end?: string };
}

export interface RouteDetail extends Omit<RouteSummary, "osm_id"> {
  /** Null for a trail assembled from mapped segments (TM05-97), which has no relation. */
  osm_id: number | null;
  /** "relation/123", or "assembled/way/456" for an assembled trail: the trail's identity. */
  source_id: string;
  geometry: MultiLineString;
  /** The route as one ordered path; every "distance along" is measured on this. */
  line: LineString & { length_m: number };
  path: { parts: number; parts_used: number; parts_left_out: number; left_out_m: number };
  profile: Profile;
  campsites: { within_m: number; count: number; truncated: boolean; items: CampsiteAlong[] };
  /** TM05-97: true when built from same-name mapped segments rather than a route relation. */
  assembled?: boolean;
  assembly?: { from_way: string; ways: number; note: string } | null;
  /** Optional so an older backend without TM05-82 still renders. */
  difficulty?: Difficulty | null;
  route_type?: RouteType;
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

/**
 * The trail for a clicked trail way (TM05-97): its route if it belongs to one, otherwise a
 * trail assembled from the connected ways with its name. Same shape as a route detail.
 */
export function fetchTrailForWay(sourceId: string, withinM: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ campsites_within_m: String(withinM) });
  const path = sourceId.split("/").map(encodeURIComponent).join("/");
  return getJson<RouteDetail>(`${API_BASE_URL}/api/trails/${path}/trail/?${params}`, signal);
}

/** One route in detail. The first request for a route can take seconds (profile). */
export function fetchRouteDetail(osmId: number, withinM: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ campsites_within_m: String(withinM) });
  return getJson<RouteDetail>(`${API_BASE_URL}/api/routes/${osmId}/?${params}`, signal);
}
