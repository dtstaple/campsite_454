/**
 * "Find campsites along this trail" (TM05-99): the candidate search's types, its request,
 * and the merged, mile-ordered result list. The merge is pure, so node --test checks it.
 */

import type { CampsiteAlong } from "./api";

export interface CandidateCheck {
  key: "public_land" | "trail" | "water" | "elevation" | "slope";
  passed: boolean;
  label: string;
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

/** The URL path of a trail's candidate search: by route, or by the way it was opened from. */
export function candidatesPath(
  detail: { osm_id: number | null; assembly?: { from_way: string } | null },
  withinM: number,
): string | null {
  const query = `?campsites_within_m=${withinM}`;
  if (detail.osm_id !== null) return `/api/routes/${detail.osm_id}/candidates/${query}`;
  const way = detail.assembly?.from_way;
  if (!way) return null;
  return `/api/trails/${way.split("/").map(encodeURIComponent).join("/")}/candidates/${query}`;
}
