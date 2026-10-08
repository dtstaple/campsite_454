/**
 * The Discover list's filters (TM05-85): the panel's state, and the API parameters it
 * becomes. Pure, so node --test can check the conversions. Lengths are entered in miles and
 * gains in feet, the units the trail panel shows; the API takes metres.
 */

export type Difficulty = "easy" | "moderate" | "hard";
export type RouteKind = "loop" | "out_and_back" | "point_to_point";

export interface TrailFilters {
  minLengthMi: string;
  maxLengthMi: string;
  minGainFt: string;
  maxGainFt: string;
  difficulty: Difficulty[];
  routeType: RouteKind[];
  /** Metres, or null for "any". */
  campsitesWithinM: number | null;
}

export const NO_FILTERS: TrailFilters = {
  minLengthMi: "",
  maxLengthMi: "",
  minGainFt: "",
  maxGainFt: "",
  difficulty: [],
  routeType: [],
  campsitesWithinM: null,
};

export const DIFFICULTY_OPTIONS: { value: Difficulty; label: string }[] = [
  { value: "easy", label: "Easy" },
  { value: "moderate", label: "Moderate" },
  { value: "hard", label: "Hard" },
];

export const ROUTE_TYPE_OPTIONS: { value: RouteKind; label: string }[] = [
  { value: "loop", label: "Loop" },
  { value: "out_and_back", label: "Out & back" },
  { value: "point_to_point", label: "Point to point" },
];

export const CAMPSITE_DISTANCE_OPTIONS = [250, 500, 1000, 2000];

const M_PER_MI = 1609.344;
const M_PER_FT = 0.3048;

function metres(raw: string, perUnit: number): string | null {
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) && value >= 0 ? String(Math.round(value * perUnit)) : null;
}

/** The API query parameters for these filters; empty or invalid fields are left out. */
export function filterParams(filters: TrailFilters): Record<string, string> {
  const params: Record<string, string> = {};
  const set = (name: string, value: string | null) => {
    if (value !== null) params[name] = value;
  };
  set("min_length_m", metres(filters.minLengthMi, M_PER_MI));
  set("max_length_m", metres(filters.maxLengthMi, M_PER_MI));
  set("min_gain_m", metres(filters.minGainFt, M_PER_FT));
  set("max_gain_m", metres(filters.maxGainFt, M_PER_FT));
  if (filters.difficulty.length) params.difficulty = [...filters.difficulty].sort().join(",");
  if (filters.routeType.length) params.route_type = [...filters.routeType].sort().join(",");
  if (filters.campsitesWithinM !== null) params.campsites_within_m = String(filters.campsitesWithinM);
  return params;
}

export function activeFilterCount(filters: TrailFilters): number {
  return Object.keys(filterParams(filters)).length;
}

/** Add `value` if it is not in `list`, remove it if it is. */
export function toggled<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

/** "3 trails have no elevation data yet, so these filters can't include them." */
export function unknownNote(unknown: number): string | null {
  if (unknown <= 0) return null;
  const trails = unknown === 1 ? "1 trail has" : `${unknown} trails have`;
  return `${trails} no elevation data yet, so these filters can't include them.`;
}
