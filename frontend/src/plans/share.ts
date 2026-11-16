/**
 * Shareable plan links (TM05-172): the pure parts, so they can be tested without a DOM.
 */

/** The full link a person can send, for a share token. */
export function shareUrl(origin: string, token: string): string {
  return `${origin.replace(/\/+$/, "")}/shared/${encodeURIComponent(token)}`;
}

export interface StripMark {
  night: number;
  label: string;
  /** Where the stop falls along the route, 0–100. */
  percent: number;
}

/** The nightly stops placed along the route, for the shared page's route strip. */
export function stripMarks(
  lengthM: number,
  stops: { night: number; display_name: string | null; distance_along_m: number }[],
): StripMark[] {
  return stops.map((stop) => ({
    night: stop.night,
    label: stop.display_name ?? "Campsite",
    percent:
      lengthM > 0 ? Math.min(100, Math.max(0, (stop.distance_along_m / lengthM) * 100)) : 0,
  }));
}
