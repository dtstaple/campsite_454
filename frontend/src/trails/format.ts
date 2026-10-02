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
