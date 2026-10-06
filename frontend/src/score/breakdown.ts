/**
 * The campsite panel's score breakdown (TM05-47), as data: what to show for a contract-1
 * score (docs/scoring.md), worked out here so node --test can check it without a DOM.
 *
 * The rule that matters: a factor that could not be evaluated (`not_available`) is shown as
 * "Not available", never as 0, so a missing input never reads as a bad site. `no_data` is
 * different -- we looked and found nothing -- and its low sub-score is real and shown.
 *
 * Anything that does not look like a contract-1 score is treated as no score at all rather
 * than half-rendered.
 */

import { distance } from "../campsite/format.ts";
import { gradeFor, isScore, type GradeLetter } from "./grade.ts";

export type FactorStatus = "scored" | "no_data" | "not_available";

export interface Factor {
  key: string;
  label: string;
  status: FactorStatus;
  score: number | null;
  contribution: number;
  measurement: Record<string, unknown> | null;
  explanation: string;
}

export interface Score {
  score: number;
  factors: Factor[];
  caps: { factor: string; max_score: number; reason: string }[];
}

const STATUSES: readonly string[] = ["scored", "no_data", "not_available"];

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const text = (value: unknown): string => (typeof value === "string" ? value : "");

/**
 * A contract-1 score, or null if `raw` is not one. Accepts the object or its JSON string
 * (MapLibre hands nested feature properties back as strings). A factor entry that is not
 * well formed is dropped; the rest still render.
 */
export function parseScore(raw: unknown): Score | null {
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!isObject(raw) || raw.contract !== 1 || !isScore(raw.score) || !Array.isArray(raw.factors)) {
    return null;
  }
  const factors: Factor[] = [];
  for (const entry of raw.factors) {
    if (!isObject(entry) || typeof entry.key !== "string" || !STATUSES.includes(entry.status as string)) {
      continue;
    }
    const status = entry.status as FactorStatus;
    factors.push({
      key: entry.key,
      label: text(entry.label) || entry.key,
      status,
      // The contract says null only when not_available; never coerce a missing score to 0.
      score: status !== "not_available" && isScore(entry.score) ? entry.score : null,
      contribution: isScore(entry.contribution) ? entry.contribution : 0,
      measurement: isObject(entry.measurement) ? entry.measurement : null,
      explanation: text(entry.explanation),
    });
  }
  const caps = Array.isArray(raw.caps)
    ? raw.caps.filter(isObject).map((cap) => ({
        factor: text(cap.factor),
        max_score: isScore(cap.max_score) ? cap.max_score : 0,
        reason: text(cap.reason),
      }))
    : [];
  return { score: raw.score, factors, caps };
}

// --- plain words ---------------------------------------------------------------------

const num = (value: unknown): number | null => (isScore(value) ? value : null);

function water(m: Record<string, unknown>): string | null {
  const metres = num(m.distance_m);
  if (metres === null) return null;
  const flow = m.perennial === true ? "perennial " : m.perennial === false ? "intermittent " : "";
  const name = text(m.name);
  return `${distance(metres)} from ${flow}${text(m.feature_type) || "water"}${name ? ` (${name})` : ""}`;
}

function trail(m: Record<string, unknown>): string | null {
  const metres = num(m.distance_m);
  if (metres === null) return null;
  const name = text(m.name);
  return `${distance(metres)} from ${name || "the nearest trail"}`;
}

const ACCESS: Record<string, string> = {
  open: "Open to the public",
  restricted: "Restricted public access",
  closed: "Closed to the public",
  unknown: "Public access unknown",
};

function legal(m: Record<string, unknown>): string | null {
  const access = ACCESS[text(m.public_access).toLowerCase()];
  if (!access) return null;
  const where = text(m.designation) || text(m.manager);
  return where ? `${access} · ${where}` : access;
}

function weather(m: Record<string, unknown>): string | null {
  const parts: string[] = [];
  const rain = num(m.precipitation_mm);
  const wind = num(m.wind_max_kmh);
  const low = num(m.temperature_min_c);
  if (rain !== null) parts.push(rain > 0 ? `${rain.toFixed(1)} mm rain` : "no rain");
  if (wind !== null) parts.push(`wind to ${Math.round(wind)} km/h`);
  if (low !== null) parts.push(`low ${Math.round(low)} °C`);
  if (!parts.length) return null;
  // The forecast changes daily, so say which day it is for (docs/scoring.md).
  const date = text(m.date);
  return `${date ? `Forecast for ${date}: ` : "Forecast: "}${parts.join(", ")}`;
}

function slope(m: Record<string, unknown>): string | null {
  const degrees = num(m.slope_deg);
  if (degrees === null) return null;
  const percent = num(m.slope_pct);
  return `Ground slope ${Math.round(degrees)}°${percent === null ? "" : ` (${Math.round(percent)}%)`}`;
}

const MEASURED: Record<string, (m: Record<string, unknown>) => string | null> = {
  water,
  trail,
  legal,
  weather,
  slope,
};

const NOTHING_FOUND: Record<string, (m: Record<string, unknown> | null) => string> = {
  water: (m) => `No water within ${distance(num(m?.max_search_m) ?? 3000)}`,
  trail: (m) => `No trail within ${distance(num(m?.max_search_m) ?? 5000)}`,
  legal: () => "Not inside any mapped public land",
};

/**
 * One line saying what was measured, in words: "62 m from perennial stream (Johns Brook)".
 * Falls back to the engine's own explanation for a factor this file does not know, so a
 * new factor shows up readable without a frontend change.
 */
export function measurementText(factor: Factor): string {
  if (factor.status === "not_available") return factor.explanation || "Not measured";
  if (factor.status === "no_data") {
    return NOTHING_FOUND[factor.key]?.(factor.measurement) ?? (factor.explanation || "Nothing found");
  }
  const words = factor.measurement ? MEASURED[factor.key]?.(factor.measurement) : null;
  return words ?? factor.explanation;
}

// --- the panel's view ----------------------------------------------------------------

export interface FactorRow {
  key: string;
  label: string;
  status: FactorStatus;
  /** "96" for a sub-score; "Not available" for not_available -- never "0". */
  value: string;
  grade: GradeLetter | null;
  detail: string;
}

export type BreakdownView =
  | { kind: "scored"; score: number; grade: GradeLetter; rows: FactorRow[]; caps: string[]; missing: number }
  /** A total from the map or a trail list, with no breakdown to go with it yet. */
  | { kind: "total-only"; score: number; grade: GradeLetter }
  | { kind: "none" };

/**
 * What the panel shows for a campsite. `raw` is the full contract-1 score if we have one;
 * `total` is a bare score from wherever the site was selected, used when `raw` is absent.
 */
export function breakdownView(raw: unknown, total: unknown = null): BreakdownView {
  const parsed = parseScore(raw);
  if (parsed) {
    return {
      kind: "scored",
      score: parsed.score,
      grade: gradeFor(parsed.score)!,
      rows: parsed.factors.map((factor) => ({
        key: factor.key,
        label: factor.label,
        status: factor.status,
        value: factor.score === null ? "Not available" : String(Math.round(factor.score)),
        grade: gradeFor(factor.score),
        detail: measurementText(factor),
      })),
      caps: parsed.caps.map((cap) => cap.reason).filter(Boolean),
      missing: parsed.factors.filter((factor) => factor.status === "not_available").length,
    };
  }
  if (isScore(total)) return { kind: "total-only", score: total, grade: gradeFor(total)! };
  return { kind: "none" };
}
