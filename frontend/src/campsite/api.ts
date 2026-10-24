/**
 * Client for GET /api/campsites/<id>/detail/ (TM05-64). Contract: docs/api.md,
 * "Campsite detail". Unknown facts arrive as null and are hidden by the panel.
 */

import { API_BASE_URL } from "../api";
import { authHeaders, storedSession } from "../auth";
import type { Feature } from "geojson";
import type { Legality } from "./legality";
import type { TerrainPayload } from "../terrain/terrain";

export interface CampsiteFactsPayload {
  public_land: {
    name: string;
    manager: string | null;
    designation: string | null;
    access: string | null;
    gap_status: string | null;
  } | null;
  water: { name: string; distance_m: number; feature_type: string | null; perennial: boolean | null } | null;
  trail: { name: string; distance_m: number; kind: "route" | "way" | "" } | null;
  terrain: { elevation_m: number; slope_deg: number; slope_pct: number } | null;
  amenities: { shelter_kind: string | null; osm_tags: Record<string, string> };
  method_version: string;
  computed_at: string;
}

/** How far to trust the record, and where and when it came from (TM05-77). */
export interface CampsiteConfidence {
  level: "official" | "community_mapped" | "limited_info";
  label: string;
  reason: string;
  source: string;
  source_label: string;
  operator: string | null;
  /** ISO 8601: when the ingest that last confirmed this record finished. */
  last_updated: string | null;
}

export interface CampsiteDetail {
  id: string;
  source: string;
  name: string | null;
  display_name: string | null;
  display_name_derived: boolean;
  site_type: string;
  reservable: boolean | null;
  lon: number;
  lat: number;
  facts: CampsiteFactsPayload | null;
  /** The score with the caller's weights; fresher than the map feature's (TM05-115). */
  score?: number | null;
  score_breakdown?: unknown;
  /** Absent from an older backend; the panel then simply omits the row. */
  confidence?: CampsiteConfidence | null;
  /** The legality verdict shown above the score (TM05-76 follow-up). */
  legality?: Legality | null;
  /** Terrain-model facts (TM05-142); null before `make terrain` has reached the site. */
  terrain?: TerrainPayload | null;
}

export class CampsiteApiError extends Error {}

/** What the terrain lets you see from the site (TM05-142), or null when there is none. */
export async function fetchViewshed(id: string, signal?: AbortSignal): Promise<Feature | null> {
  const path = id.split("/").map(encodeURIComponent).join("/");
  const response = await fetch(`${API_BASE_URL}/api/campsites/${path}/viewshed/`, { signal });
  if (response.status === 404) return null;
  if (!response.ok) throw new CampsiteApiError(`HTTP ${response.status}`);
  return (await response.json()) as Feature;
}

/** The id contains a slash ("node/5759412256"); each part is encoded, the slash kept. */
export function detailUrl(id: string): string {
  const path = id.split("/").map(encodeURIComponent).join("/");
  return `${API_BASE_URL}/api/campsites/${path}/detail/`;
}

export async function fetchCampsiteDetail(id: string, signal?: AbortSignal): Promise<CampsiteDetail> {
  let response: Response;
  try {
    // Signed in, the score uses the user's own weights (TM05-46).
    response = await fetch(detailUrl(id), { signal, headers: authHeaders(storedSession()) });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new CampsiteApiError(`Could not reach the API at ${API_BASE_URL}.`);
  }
  if (response.status === 404) throw new CampsiteApiError("That campsite is no longer in the data.");
  if (!response.ok) throw new CampsiteApiError(`HTTP ${response.status}`);
  return (await response.json()) as CampsiteDetail;
}
