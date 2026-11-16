/**
 * The natural-language trip finder on Discover trails (TM05-170). Pure, so node --test can
 * load it.
 *
 * The server reads the sentence (POST /api/discover/interpret/, docs/api.md); this turns
 * its reading into the page's own filters, so the results come from the same trail search
 * as the Filters panel. The chips are drawn from those filters, so editing one in the panel
 * or removing a chip changes the search exactly as the panel would.
 */

import { NO_FILTERS, type Difficulty, type RouteKind, type TrailFilters } from "../trails/filters.ts";

const FT_PER_M = 3.28084;

export interface Interpretation {
  min_length_mi: number | null;
  max_length_mi: number | null;
  min_gain_ft: number | null;
  max_gain_ft: number | null;
  difficulty: Difficulty[];
  route_type: RouteKind[];
  nights: number | null;
  has_campsites: boolean | null;
  water_view: boolean | null;
  sheltered: boolean | null;
  region: string | null;
  weights: Record<string, number | null> | null;
  unsupported: string[];
}

export interface InterpretAnswer {
  text: string;
  source: "llm" | "keywords";
  fallback_reason: "no_key" | "timeout" | "api_error" | "invalid_output" | null;
  model: string | null;
  interpretation: Interpretation;
  search: Record<string, string>;
  not_filtered: string[];
  empty: boolean;
  cached: boolean;
}

/** What the reading shows but the trail search can't filter on. */
export interface Extras {
  nights: number | null;
  waterView: boolean | null;
  sheltered: boolean | null;
  weights: Record<string, number> | null;
}

export const NO_EXTRAS: Extras = { nights: null, waterView: null, sheltered: null, weights: null };

function text(value: number | null): string {
  return value === null ? "" : String(Math.round(value * 10) / 10);
}

/** The page's filters for a reading: the same filters the server's `search` holds. */
export function filtersFrom(answer: Pick<InterpretAnswer, "interpretation" | "search">): TrailFilters {
  const read = answer.interpretation;
  const within = answer.search.campsites_within_m;
  return {
    ...NO_FILTERS,
    minLengthMi: text(read.min_length_mi),
    maxLengthMi: text(read.max_length_mi),
    minGainFt: text(read.min_gain_ft),
    maxGainFt: text(read.max_gain_ft),
    difficulty: [...read.difficulty],
    routeType: [...read.route_type],
    campsitesWithinM: within ? Number(within) : null,
  };
}

export function extrasFrom(read: Interpretation): Extras {
  const weights = read.weights
    ? Object.fromEntries(
        Object.entries(read.weights).filter((entry): entry is [string, number] => entry[1] !== null),
      )
    : null;
  return {
    nights: read.nights,
    waterView: read.water_view,
    sheltered: read.sheltered,
    weights: weights && Object.keys(weights).length ? weights : null,
  };
}

export interface Chip {
  key: string;
  label: string;
  /** "filter" chips narrow the trail search; "shown" chips are read but not searched on. */
  kind: "filter" | "shown";
  note?: string;
}

const ROUTE_LABELS: Record<RouteKind, string> = {
  loop: "Loop",
  out_and_back: "Out & back",
  point_to_point: "Point to point",
};

function capital(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function range(low: string, high: string, unit: string): string {
  if (low && high) return `${low}–${high} ${unit}`;
  if (high) return `Under ${high} ${unit}`;
  return `Over ${low} ${unit}`;
}

/** The chips for the current filters and extras, in reading order. */
export function chipsFor(filters: TrailFilters, extras: Extras, regionLabel: string | null): Chip[] {
  const chips: Chip[] = [];
  if (regionLabel) chips.push({ key: "region", label: regionLabel, kind: "filter" });
  if (filters.minLengthMi || filters.maxLengthMi) {
    chips.push({ key: "length", label: range(filters.minLengthMi, filters.maxLengthMi, "mi"), kind: "filter" });
  }
  if (filters.minGainFt || filters.maxGainFt) {
    chips.push({ key: "gain", label: `${range(filters.minGainFt, filters.maxGainFt, "ft")} climb`, kind: "filter" });
  }
  for (const level of filters.difficulty) {
    chips.push({ key: `difficulty:${level}`, label: capital(level), kind: "filter" });
  }
  for (const kind of filters.routeType) {
    chips.push({ key: `route:${kind}`, label: ROUTE_LABELS[kind], kind: "filter" });
  }
  if (filters.campsitesWithinM !== null) {
    chips.push({
      key: "campsites",
      label: `Campsites within ${Math.round(filters.campsitesWithinM * FT_PER_M).toLocaleString("en-US")} ft`,
      kind: "filter",
    });
  }
  if (extras.nights !== null) {
    const label = extras.nights === 0 ? "Day hike" : `${extras.nights} night${extras.nights === 1 ? "" : "s"}`;
    const note = extras.nights === 0 ? "Not a trail filter" : "A night out needs a campsite: see the campsites filter";
    chips.push({ key: "nights", label, kind: "shown", note });
  }
  if (extras.waterView !== null) {
    chips.push({
      key: "water_view",
      label: extras.waterView ? "Water view" : "No water view",
      kind: "shown",
      note: "Shown on campsites, not a trail filter yet",
    });
  }
  if (extras.sheltered !== null) {
    chips.push({
      key: "sheltered",
      label: extras.sheltered ? "Sheltered" : "Not sheltered",
      kind: "shown",
      note: "Shown on campsites, not a trail filter yet",
    });
  }
  if (extras.weights) {
    const parts = Object.entries(extras.weights).map(([name, weight]) => `${name.replace("_", " ")} ${weight}`);
    chips.push({
      key: "weights",
      label: `Weights: ${parts.join(", ")}`,
      kind: "shown",
      note: "Set scoring weights in Profile",
    });
  }
  return chips;
}

/** The filters and extras with one chip taken out. */
export function withoutChip(
  key: string,
  filters: TrailFilters,
  extras: Extras,
): { filters: TrailFilters; extras: Extras } {
  const f = { ...filters };
  const e = { ...extras };
  if (key === "length") Object.assign(f, { minLengthMi: "", maxLengthMi: "" });
  else if (key === "gain") Object.assign(f, { minGainFt: "", maxGainFt: "" });
  else if (key.startsWith("difficulty:")) f.difficulty = f.difficulty.filter((d) => `difficulty:${d}` !== key);
  else if (key.startsWith("route:")) f.routeType = f.routeType.filter((r) => `route:${r}` !== key);
  else if (key === "campsites") f.campsitesWithinM = null;
  else if (key === "nights") e.nights = null;
  else if (key === "water_view") e.waterView = null;
  else if (key === "sheltered") e.sheltered = null;
  else if (key === "weights") e.weights = null;
  return { filters: f, extras: e };
}

/** "Crowding isn't something we can measure yet." */
export function unsupportedLine(ask: string): string {
  return `${capital(ask.trim())} isn't something we can measure yet.`;
}

/** The small note when the keyword parser read the request, or null when the model did. */
export function fallbackNote(answer: Pick<InterpretAnswer, "source" | "fallback_reason">): string | null {
  if (answer.source === "llm") return null;
  const why =
    answer.fallback_reason === "no_key"
      ? "The AI reader isn't set up here"
      : answer.fallback_reason === "timeout"
        ? "The AI reader took too long"
        : "The AI reader's answer couldn't be used";
  return `${why}, so a simple keyword reader read your request. Check the chips.`;
}
