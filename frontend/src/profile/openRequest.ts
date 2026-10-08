/**
 * What the map should open when a Profile item is clicked (TM05-100). Pure, so node --test
 * checks that each kind of item opens the right panel.
 *
 * The Profile page navigates to /discover with one of these in the router state, and the
 * map page acts on it once: a campsite opens the campsite panel (with the raised pin,
 * TM05-69), a trail or a plan opens the trail panel (the plan loaded into it), and a
 * waypoint opens its editor. Each flies the map there, whatever layers are on.
 */

export type OpenRequest =
  | { kind: "campsite"; id: string; lon: number; lat: number; name: string }
  | { kind: "trail"; trail: TrailTarget; name: string }
  | { kind: "plan"; planId: number; trail: TrailTarget; name: string }
  | { kind: "waypoint"; id: number; lon: number; lat: number; name: string };

export type TrailTarget = { osmId: number } | { wayId: string };

/** The router state key the map page reads. */
export const OPEN_STATE_KEY = "open";

export function campsiteRequest(saved: {
  id: string;
  lon: number;
  lat: number;
  name: string;
}): OpenRequest {
  return { kind: "campsite", id: saved.id, lon: saved.lon, lat: saved.lat, name: saved.name };
}

function trailTarget(row: { osm_id: number | null; from_way: string | null }): TrailTarget | null {
  if (row.osm_id !== null) return { osmId: row.osm_id };
  if (row.from_way) return { wayId: row.from_way };
  return null;
}

export function trailRequest(saved: {
  osm_id: number | null;
  from_way: string | null;
  name: string;
}): OpenRequest | null {
  const trail = trailTarget(saved);
  return trail ? { kind: "trail", trail, name: saved.name } : null;
}

export function planRequest(plan: {
  id: number;
  osm_id: number | null;
  from_way: string | null;
  trail_name: string;
}): OpenRequest | null {
  const trail = trailTarget(plan);
  return trail ? { kind: "plan", planId: plan.id, trail, name: plan.trail_name } : null;
}

export function waypointRequest(waypoint: {
  id: number;
  lon: number;
  lat: number;
  name: string;
}): OpenRequest {
  return { kind: "waypoint", id: waypoint.id, lon: waypoint.lon, lat: waypoint.lat, name: waypoint.name };
}

/** Which panel a request opens: what the Profile promises and the tests check. */
export function panelFor(request: OpenRequest): "campsite" | "trail" | "waypoint" {
  if (request.kind === "campsite") return "campsite";
  if (request.kind === "waypoint") return "waypoint";
  return "trail";
}

/** Read a request back out of router state, defensively: state is whatever was pushed. */
export function requestFromState(state: unknown): OpenRequest | null {
  if (!state || typeof state !== "object") return null;
  const value = (state as Record<string, unknown>)[OPEN_STATE_KEY];
  if (!value || typeof value !== "object") return null;
  const kind = (value as { kind?: unknown }).kind;
  return kind === "campsite" || kind === "trail" || kind === "plan" || kind === "waypoint"
    ? (value as OpenRequest)
    : null;
}
