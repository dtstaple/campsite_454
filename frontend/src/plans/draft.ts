/**
 * The plan being built in the trail panel (TM05-81). Pure, so node --test can load it.
 *
 * A draft belongs to one trail, by the detail's `source_id` ("relation/123", or
 * "assembled/way/456"). Opening another trail shows an empty draft without anything
 * having to clear the old one: `draftFor` simply does not match it.
 */

export interface PlanDraft {
  trailKey: string;
  stopIds: string[];
  /** The saved plan this draft edits, or null for a new one. */
  planId: number | null;
  name: string;
}

export function emptyDraft(trailKey: string): PlanDraft {
  return { trailKey, stopIds: [], planId: null, name: "" };
}

export function draftFor(draft: PlanDraft | null, trailKey: string): PlanDraft {
  return draft && draft.trailKey === trailKey ? draft : emptyDraft(trailKey);
}

/** Add the campsite as a stop, or take it out if it is one. */
export function toggleStop(draft: PlanDraft, id: string): PlanDraft {
  const has = draft.stopIds.includes(id);
  return { ...draft, stopIds: has ? draft.stopIds.filter((s) => s !== id) : [...draft.stopIds, id] };
}

/** The API's name for the trail a detail is: its route, the way it was assembled from,
 * or (TM05-119) a planned route's id. */
export function trailRef(detail: {
  osm_id: number | null;
  assembly?: { from_way: string } | null;
  planned?: { id: string } | null;
}): { osm_id: number } | { from_way: string } | { planned_route: string } | null {
  if (detail.planned) return { planned_route: detail.planned.id };
  if (detail.osm_id !== null) return { osm_id: detail.osm_id };
  if (detail.assembly?.from_way) return { from_way: detail.assembly.from_way };
  return null;
}

/** "2 nights", "1 night". */
export function nights(count: number): string {
  return `${count} night${count === 1 ? "" : "s"}`;
}

/** A plan's GPX file name, as the API would give it. */
export function planFilename(name: string): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `${slug || "plan"}.gpx`;
}

/** The saved-trail row for a trail (TM05-100), if this trail is saved. */
export function savedRowFor<T extends { osm_id: number | null; from_way: string | null }>(
  saved: readonly T[],
  trail: { osm_id: number } | { from_way: string } | { planned_route: string } | null,
): T | null {
  // A planned route (TM05-119) is never a saved trail: saved trails are routes and ways.
  if (!trail || "planned_route" in trail) return null;
  if ("osm_id" in trail) return saved.find((row) => row.osm_id === trail.osm_id) ?? null;
  return saved.find((row) => row.osm_id === null && row.from_way === trail.from_way) ?? null;
}
