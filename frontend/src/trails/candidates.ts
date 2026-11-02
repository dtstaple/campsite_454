/**
 * "Find campsites along this trail" (TM05-99): the candidate search's types, its request,
 * and the merged, mile-ordered result list. The merge is pure, so node --test checks it.
 */

import type { CampsiteAlong } from "./api";
import type { TerrainBadges } from "../terrain/terrain";

export interface CandidateCheck {
  key: "public_land" | "trail" | "water" | "pooling" | "elevation" | "slope";
  passed: boolean;
  label: string;
}

/** TM05-153: one terrain zone that moved a spot up (points > 0) or down the ranking. */
export interface TerrainReason {
  key: string;
  label: string;
  points: number;
}

/** A computed spot, never a mapped campsite. Contract: docs/api.md, "Potential campsites". */
export interface Candidate {
  id: string;
  kind: "candidate";
  label: string;
  lon: number;
  lat: number;
  distance_along_m: number;
  distance_from_route_m: number;
  side: "left" | "right";
  score: number | null;
  checks: CandidateCheck[];
  not_checked: string;
  rule: { text: string; source: string } | null;
  confidence: { level: "computed"; label: string; reason: string };
  elevation_m: number;
  slope_deg: number;
  /** TM05-143: what the terrain zones say (exposure); absent from an older API. */
  terrain?: TerrainBadges | null;
  /** TM05-153: the score plus or minus its terrain, which ordered the search. */
  rank?: number | null;
  /** TM05-153: why its terrain ranked it, best first; absent from an older API. */
  terrain_reasons?: TerrainReason[];
}

/** "+8", "−5": a reason's points, with a real minus sign. */
export function signedPoints(points: number): string {
  const rounded = Math.round(points);
  if (rounded === 0) return "0";
  return rounded > 0 ? `+${rounded}` : `−${Math.abs(rounded)}`;
}

/** The short name of a reason: "Sheltered: lower than..." reads "sheltered". */
function shortReason(reason: TerrainReason): string {
  return reason.label.split(":")[0].toLowerCase();
}

/**
 * The one-line terrain summary on a candidate's list row: the net points and the reasons,
 * e.g. "Terrain +8: sheltered" or "Terrain −5: exposed, high ground". Null when terrain
 * set the spot apart in neither direction.
 */
export function terrainSummary(candidate: Pick<Candidate, "terrain_reasons">): string | null {
  const reasons = candidate.terrain_reasons ?? [];
  if (reasons.length === 0) return null;
  const net = reasons.reduce((sum, reason) => sum + reason.points, 0);
  return `Terrain ${signedPoints(net)}: ${reasons.map(shortReason).join(", ")}`;
}

export interface CandidateSearch {
  status: "ok" | "unavailable";
  within_m: number;
  candidates: Candidate[];
  counts: {
    sampled: number;
    rejected: Record<string, number>;
    passed: number;
    scored?: number;
    kept: number;
  } | null;
  reason: string | null;
  cached?: boolean;
}

/** One row of the trail's "places to camp" list: a mapped campsite or a candidate. */
export type AlongResult =
  | { kind: "campsite"; id: string; distance_along_m: number; site: CampsiteAlong }
  | { kind: "candidate"; id: string; distance_along_m: number; candidate: Candidate };

/**
 * Mapped campsites and candidates in one list, by mile. Campsites past either end of the
 * trail (TM05-73) have no true mile; they keep their position at the start or end.
 */
export function alongResults(
  campsites: readonly CampsiteAlong[],
  candidates: readonly Candidate[],
): AlongResult[] {
  const rows: AlongResult[] = [
    ...campsites.map((site) => ({
      kind: "campsite" as const,
      id: site.id,
      distance_along_m: site.distance_along_m,
      site,
    })),
    ...candidates.map((candidate) => ({
      kind: "candidate" as const,
      id: candidate.id,
      distance_along_m: candidate.distance_along_m,
      candidate,
    })),
  ];
  return rows.sort((a, b) => a.distance_along_m - b.distance_along_m || a.id.localeCompare(b.id));
}

/** The summary under the list once the search is back. */
export function searchSummary(mapped: number, search: CandidateSearch | null): string {
  const places = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  if (!search) return places(mapped, "mapped campsite");
  if (search.status !== "ok") return `${places(mapped, "mapped campsite")}. Potential spots are unavailable right now.`;
  const found = search.candidates.length;
  return `${places(mapped, "mapped campsite")} and ${places(found, "potential spot")}.`;
}

/** The URL path of a trail's candidate search: by route, by the way it was opened from,
 * or (TM05-119) by a planned route's id. */
export function candidatesPath(
  detail: {
    osm_id: number | null;
    assembly?: { from_way: string } | null;
    planned?: { id: string } | null;
  },
  withinM: number,
): string | null {
  const query = `?campsites_within_m=${withinM}`;
  if (detail.planned) return `/api/routing/${detail.planned.id}/candidates/${query}`;
  if (detail.osm_id !== null) return `/api/routes/${detail.osm_id}/candidates/${query}`;
  const way = detail.assembly?.from_way;
  if (!way) return null;
  return `/api/trails/${way.split("/").map(encodeURIComponent).join("/")}/candidates/${query}`;
}
