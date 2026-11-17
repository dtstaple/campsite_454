/**
 * TM05-171: how hard a campsite is to reach from the nearest reachable trailhead,
 * precomputed by the pipeline (`compute_access`). "unknown" means no trailhead connects
 * to the site's trails; its figures are then null, never guessed.
 */
export type AccessClass = "easy" | "moderate" | "hard" | "unknown";

export interface Access {
  class: AccessClass;
  label: string;
  /** One line: the walk, its trailhead, and the limit it is within or over. */
  reason: string;
  trailhead: string | null;
  distance_m: number | null;
  gain_m: number | null;
  time_s: number | null;
}

/** The "Easy access" quick filter. Unknown or not-yet-computed access fails: a filter
 * shows what is known to qualify, never a guess. */
export function passesAccessFilter(access: Access | null | undefined, easyOnly: boolean): boolean {
  if (!easyOnly) return true;
  return access?.class === "easy";
}

/** The panel row's text: the class label, with the reason beneath. */
export function accessText(access: Access | null | undefined): { label: string; reason: string } | null {
  if (!access) return null;
  return { label: access.label, reason: access.reason };
}
