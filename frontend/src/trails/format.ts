/**
 * Units and estimates for the trail panel.
 *
 * Distances and heights are shown in miles and feet: these are US trails, and trail signs,
 * guidebooks and the published figures hikers compare against all use them. The data stays
 * metric underneath.
 */

/** Search radii offered for "campsites along this trail", in metres. */
export const WITHIN_OPTIONS = [250, 500, 1000, 2000];

const M_PER_MI = 1609.344;
const FT_PER_M = 3.28084;

export function miles(metres: number, digits = 1): string {
  return `${(metres / M_PER_MI).toFixed(digits)} mi`;
}

export function feet(metres: number): string {
  return `${Math.round(metres * FT_PER_M).toLocaleString()} ft`;
}

export function percent(value: number): string {
  return `${Math.round(value)}%`;
}

/**
 * Naismith's rule: 1 hour per 5 km of distance, plus 1 hour per 600 m of ascent.
 * A planning figure for a fit hiker with a light pack, excluding breaks.
 */
export function naismithMinutes(distanceM: number, gainM: number): number {
  return (distanceM / 5000) * 60 + (gainM / 600) * 60;
}

export function duration(minutes: number): string {
  const rounded = Math.round(minutes / 5) * 5;
  const h = Math.floor(rounded / 60);
  const m = rounded % 60;
  if (h === 0) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

const END_WORDS: Record<string, string> = {
  summit: "a summit",
  pond: "a pond",
  connects: "other trails",
  dead_end: "a dead end",
};

/** "Out & back (est.)", and the hover text saying what the guess rests on (TM05-82). */
export function routeTypeText(routeType: {
  label: string;
  estimated: boolean;
  basis: { ends_apart_m: number; start?: string; end?: string };
}): { value: string; hint: string } {
  if (!routeType.estimated) {
    return {
      value: routeType.label,
      hint: `Start and end are ${Math.round(routeType.basis.ends_apart_m)} m apart`,
    };
  }
  const start = END_WORDS[routeType.basis.start ?? ""] ?? "unknown";
  const end = END_WORDS[routeType.basis.end ?? ""] ?? "unknown";
  return {
    value: `${routeType.label} (est.)`,
    hint: `Estimated from its ends: one meets ${start}, the other ${end}. Roads are not mapped, so a trailhead can read as a dead end.`,
  };
}

/** True when a listed campsite has a real place along the route (TM05-73). */
export function isAlong(site: { position?: string }): boolean {
  return !site.position || site.position === "along";
}

/**
 * The trail list's mile column and the line under the name. A site past either end gets
 * no mile: "—", and "near the trailhead · 763 m away" instead of "mi 0.0 … 763 m off trail".
 */
export function campsitePlace(site: {
  distance_along_m: number;
  distance_from_route_m: number;
  position?: string;
  position_label?: string | null;
}): { mile: string; off: string } {
  const off = Math.round(site.distance_from_route_m);
  if (!isAlong(site) && site.position_label) {
    return { mile: "—", off: `${site.position_label} · ${off} m away` };
  }
  return { mile: `mi ${(site.distance_along_m / 1609.344).toFixed(1)}`, off: `${off} m off trail` };
}

/** The name the trail list shows, and whether it was derived (TM05-71). Falls back to the
 * source name, then to "Unnamed campsite", for an API without display names. */
export function campsiteName(site: {
  name: string | null;
  display_name?: string | null;
  display_name_derived?: boolean;
}): { text: string; derived: boolean } {
  if (site.display_name) return { text: site.display_name, derived: Boolean(site.display_name_derived) };
  return { text: site.name ?? "Unnamed campsite", derived: false };
}

/** A trail way that can open the trail panel (TM05-97): one with a name. Unnamed segments
 * keep the small popup. */
export function isNamedTrail(properties: Record<string, unknown> | null | undefined): boolean {
  const name = properties?.name;
  return typeof name === "string" && name.trim() !== "";
}
