/**
 * Routes planned across connected trails (TM05-119). Pure, so node --test can load it.
 *
 * A planned route has no row: it is named by its route id, "<region>:<cost>:<node>,...",
 * the OSM nodes of the stops the user chose (backend routing/service.py). The API solves
 * it again from that id, so the id is all the trail panel, the plan and the GPX need.
 */

export type Cost = "naismith" | "distance";

export const COSTS: { id: Cost; label: string; hint: string }[] = [
  { id: "naismith", label: "Quickest", hint: "Naismith's rule: 5 km/h plus 1 h per 600 m of climb" },
  { id: "distance", label: "Shortest", hint: "The fewest miles, whatever the climb" },
];

export interface PlannedStop {
  node_id: number;
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
  /** Every trail the route uses, in the order it first reaches it. */
  trails: { name: string; length_m: number }[];
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

/** Remove the stop at `index`; the others keep their order. */
export function withoutStop<T>(stops: readonly T[], index: number): T[] {
  return stops.filter((_, i) => i !== index);
}
