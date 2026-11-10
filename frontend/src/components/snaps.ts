/**
 * Bottom sheets on a phone (TM05-103): the three heights a panel snaps to, and which one a
 * drag ends nearest. Pure, so node --test checks it.
 */

export type Snap = "peek" | "half" | "full";
export const SNAPS: readonly Snap[] = ["peek", "half", "full"];

/** At most this tall (px), the map area is short: a phone on its side (TM05-134). */
export const SHORT_AVAILABLE_PX = 500;
/** On a short map, the share of it a full sheet always leaves uncovered. */
export const SHORT_MAP_KEPT = 0.4;
/** On a short map, the largest share of it a peeking sheet covers. */
export const SHORT_PEEK_SHARE = 0.3;
/** The smallest peek: the handle and the panel's title line. */
export const MIN_PEEK_PX = 72;

/**
 * Pixel heights for a map area `available` px tall: peek shows the panel's header and a
 * line under it; half is half the map; full leaves a strip of map at the top so the sheet
 * still reads as a sheet.
 *
 * On a short map (a phone in landscape, ~390 px of screen and less of map) the fixed
 * sizes would leave a sliver: full keeps SHORT_MAP_KEPT of the map visible, and peek
 * shrinks to SHORT_PEEK_SHARE of it, so the map stays usable at every snap. A taller map
 * gets the original sizes.
 */
export function snapHeights(available: number, peek = 132, topGap = 56): Record<Snap, number> {
  const short = available <= SHORT_AVAILABLE_PX;
  const peekPx = short
    ? Math.min(peek, Math.max(MIN_PEEK_PX, Math.round(available * SHORT_PEEK_SHARE)))
    : peek;
  const mapKept = short ? Math.max(topGap, Math.round(available * SHORT_MAP_KEPT)) : topGap;
  const full = Math.max(peekPx, available - mapKept);
  const half = Math.min(full, Math.max(peekPx, Math.round(available / 2)));
  return { peek: Math.min(peekPx, full), half, full };
}

/** The snap a drag that ended at `height` (px) settles on. A fast flick moves one step. */
export function nearestSnap(
  height: number,
  heights: Record<Snap, number>,
  velocity = 0,
  current?: Snap,
): Snap {
  if (current && Math.abs(velocity) > 0.6) {
    const index = SNAPS.indexOf(current);
    const next = velocity < 0 ? Math.min(index + 1, SNAPS.length - 1) : Math.max(index - 1, 0);
    return SNAPS[next];
  }
  return SNAPS.reduce((best, snap) =>
    Math.abs(heights[snap] - height) < Math.abs(heights[best] - height) ? snap : best,
  );
}

/** A tap on the handle steps up through the sizes, and from full back to peek. */
export function nextSnap(current: Snap): Snap {
  return SNAPS[(SNAPS.indexOf(current) + 1) % SNAPS.length];
}
