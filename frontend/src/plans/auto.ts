/**
 * Auto-plan in the Overnight plan section (TM05-169). Pure, so node --test can load it.
 *
 * The server chooses the stops (POST /api/plans/auto/, docs/api.md "Auto-planned stops");
 * this turns the form into a request, and matches the answer's reasons to the draft. The
 * answer opens as an ordinary draft: once the user adds or removes a night, the reasons
 * no longer describe the plan, so they are hidden.
 */

const M_PER_MI = 1609.344;

export type AutoMode = "nights" | "miles";

export type AutoBody = { nights: number } | { daily_target_m: number };

export interface AutoChoice {
  night: number;
  id: string;
  name: string;
  distance_along_m: number;
  score: number | null;
  window_start_m: number;
  window_end_m: number;
  legal_options: number;
  other_options: number;
  reason: string;
}

export interface AutoGap {
  night: number;
  from_m: number;
  to_m: number;
  unverified: number;
  message: string;
}

export interface AutoConsidered {
  within_m: number;
  mapped: number;
  mapped_permitted: number;
  mapped_truncated: boolean;
  candidates_searched: boolean;
  candidates: number | null;
}

export interface AutoPlanAnswer<Plan = unknown> {
  status: "ok" | "partial" | "none";
  mode: "nights" | "daily_target";
  nights_requested: number;
  nights_planned: number;
  day_target_m: number;
  stop_ids: string[];
  choices: AutoChoice[];
  gaps: AutoGap[];
  considered: AutoConsidered;
  plan: Plan | null;
}

/** The request for the form's values, or a sentence saying what to fix. */
export function autoBody(mode: AutoMode, raw: string): AutoBody | { error: string } {
  const value = Number(raw.trim());
  if (!raw.trim() || !Number.isFinite(value) || value <= 0) {
    return { error: mode === "nights" ? "Enter a number of nights." : "Enter miles a day." };
  }
  if (mode === "nights") {
    if (!Number.isInteger(value)) return { error: "Enter a whole number of nights." };
    return { nights: value };
  }
  return { daily_target_m: Math.round(value * M_PER_MI) };
}

/** True when the draft's stops are exactly the auto-plan's, in any order. */
export function sameStops(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const set = new Set(a);
  return b.every((id) => set.has(id));
}

/** Each chosen stop's reason, by stop id. */
export function reasonsByStop(answer: Pick<AutoPlanAnswer, "choices">): Map<string, string> {
  return new Map(answer.choices.map((choice) => [choice.id, choice.reason]));
}

/** One line on what the planner looked at. Potential spots are never chosen, because
 * their legality is unverified; the line says so. */
export function consideredLine(answer: Pick<AutoPlanAnswer, "considered" | "nights_planned">) {
  const { mapped, mapped_permitted, candidates, candidates_searched } = answer.considered;
  const planned = `${answer.nights_planned} night${answer.nights_planned === 1 ? "" : "s"}`;
  const spots = candidates_searched
    ? `Find campsites found ${candidates}`
    : "Find campsites hasn't been run here";
  return (
    `Auto-planned ${planned} from ${mapped_permitted} legal of ${mapped} mapped ` +
    `campsite${mapped === 1 ? "" : "s"}. Only Permitted stops are chosen: potential spots ` +
    `are unverified, so they are never chosen automatically (${spots}).`
  );
}
