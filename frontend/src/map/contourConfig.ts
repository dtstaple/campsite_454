/**
 * Contour intervals (TM05-83). Pure, so node --test can load it; contours.ts draws them.
 *
 * In feet, like a USGS topo: 40 ft contours with a 200 ft index line at zoom 12-13, then
 * 20 ft with a 100 ft index from zoom 14, where a 40 ft interval leaves gentle ground
 * blank. The index line is always the fifth, which is what makes a map count-able:
 * maplibre-contour tags a line level 1 when its elevation is a multiple of the index.
 */

export const FT_PER_M = 3.28084;

/** Contours appear from this zoom. Below it, 40 ft lines are a solid smear. */
export const CONTOUR_MIN_ZOOM = 12;

/** zoom -> [interval, index interval] in feet. Zooms in between use the one below. */
export const CONTOUR_THRESHOLDS_FT: Readonly<Record<number, [number, number]>> = {
  12: [40, 200],
  13: [40, 200],
  14: [20, 100],
  15: [20, 100],
};

/** Every fifth line is an index line, at every zoom. */
export const INDEX_EVERY = 5;

/** The level maplibre-contour gives an index line (`levelKey`), 0 for the rest. */
export const INDEX_LEVEL = 1;

/** A label: "1,240 ft". */
export function contourLabel(feet: number): string {
  return `${Math.round(feet).toLocaleString("en-US")} ft`;
}

/** The interval and index at a zoom, as maplibre-contour would choose them. */
export function intervalsAt(zoom: number): [number, number] | null {
  const zooms = Object.keys(CONTOUR_THRESHOLDS_FT)
    .map(Number)
    .filter((z) => z <= Math.floor(zoom))
    .sort((a, b) => b - a);
  return zooms.length ? CONTOUR_THRESHOLDS_FT[zooms[0]] : null;
}

/** Whether an elevation (feet) falls on an index line at this zoom. */
export function isIndex(feet: number, zoom: number): boolean {
  const intervals = intervalsAt(zoom);
  return intervals !== null && Math.round(feet) % intervals[1] === 0;
}
