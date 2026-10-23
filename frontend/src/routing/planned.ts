/**
 * Routes planned across connected trails (TM05-119). Pure, so node --test can load it.
 *
 * A planned route has no row: it is named by its route id, "<region>:<cost>:<node>,...",
 * the OSM nodes of the stops the user chose (backend routing/service.py). The API solves
 * it again from that id, so the id is all the trail panel, the plan and the GPX need.
 */

export type Cost = "naismith" | "distance";

/** Where a route runs (TM05-137): trail, a track, a road walk between trails, or a short
 * gap the map leaves between two trails that meet. */
export type PlannedKind = "trail" | "track" | "road walk" | "gap bridged";

/** The nearest point a connected route could start from, when the API can't route. */
export interface RouteSuggestion {
  lon: number;
  lat: number;
  trail_name: string;
  distance_m: number;
  /** "start" to move the start there; "stop" to move the stop that wasn't reachable. */
  instead_of: "start" | "stop";
}

export const COSTS: { id: Cost; label: string; hint: string }[] = [
  { id: "naismith", label: "Quickest", hint: "Naismith's rule: 5 km/h plus 1 h per 600 m of climb" },
  { id: "distance", label: "Shortest", hint: "The fewest miles, whatever the climb" },
];

export interface PlannedStop {
  /** The stop in the route id: "w<way>-<decimetres>" on a trail, or an OSM node id. */
  token: string;
  /** Null for a point between junctions (TM05-137 snaps to the nearest segment). */
  node_id: number | null;
  lon: number;
  lat: number;
  trail_name: string;
  /** Click to trail, metres; null when the route was opened from its id. */
  snapped_m: number | null;
}

export interface PlannedLeg {
  from: string;
  to: string;
  length_m: number;
  ascent_m: number;
  descent_m: number;
  naismith_s: number;
}

export interface PlannedBlock {
  id: string;
  region: string;
  cost: Cost;
  stops: PlannedStop[];
  legs: PlannedLeg[];
  /** Every trail, track, road walk and bridged gap the route uses, in the order it first
   * reaches it (TM05-137). */
  trails: { name: string; kind: PlannedKind; length_m: number }[];
  /** How much of the route leaves trail. */
  off_trail?: { road_walk_m: number; track_m: number; bridged_m: number };
  /** The graph's own totals (50 m samples); the profile's stats are the panel's. */
  graph_totals: { length_m: number; ascent_m: number; descent_m: number; naismith_s: number };
  timing_ms: Record<string, number | boolean>;
}

/** The API path (no host) of a planned route, or of its candidates or GPX. */
export function routingPath(id: string, part: "" | "candidates" | "gpx", withinM: number): string {
  const tail = part ? `${part}/` : "";
  return `/api/routing/${id}/${tail}?campsites_within_m=${withinM}`;
}

/** Labels for the stops picked so far: the first is the start, the last the end. */
export function stopLabels(count: number): string[] {
  if (count <= 0) return [];
  if (count === 1) return ["Start"];
  return ["Start", ...Array.from({ length: count - 2 }, (_, i) => `Stop ${i + 1}`), "End"];
}

/** "4 h 35 min", "50 min". */
export function duration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} min`;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

/** "Includes 0.2 mi of road walk and 0.1 mi of track", or null when it never leaves trail.
 * Bridged gaps are a few metres, so they are only named when they reach 0.1 mi. */
export function offTrailNote(
  off: { road_walk_m: number; track_m: number; bridged_m: number } | undefined,
  formatDistance: (m: number) => string,
): string | null {
  if (!off) return null;
  const parts: string[] = [];
  if (off.road_walk_m >= 1) parts.push(`${formatDistance(off.road_walk_m)} of road walk`);
  if (off.track_m >= 1) parts.push(`${formatDistance(off.track_m)} of track`);
  if (off.bridged_m >= 160) parts.push(`${formatDistance(off.bridged_m)} across map gaps`);
  if (parts.length === 0) return null;
  return `Includes ${parts.join(" and ")}.`;
}

/** The stops with the suggested point in place of the start (or the last stop). */
export function withSuggestion(
  stops: readonly [number, number][],
  suggestion: RouteSuggestion,
): [number, number][] {
  const point: [number, number] = [suggestion.lon, suggestion.lat];
  if (stops.length === 0) return [point];
  if (suggestion.instead_of === "start") return [point, ...stops.slice(1)];
  return [...stops.slice(0, -1), point];
}

/** A stretch's length: miles, or feet under a tenth of a mile, so a 60 m road walk
 * reads "197 ft", not "0.0 mi". */
export function stretch(metres: number, formatMiles: (m: number) => string): string {
  return metres < 160.9344 ? `${Math.round(metres * 3.28084).toLocaleString("en-US")} ft` : formatMiles(metres);
}

/** Remove the stop at `index`; the others keep their order. */
export function withoutStop<T>(stops: readonly T[], index: number): T[] {
  return stops.filter((_, i) => i !== index);
}
