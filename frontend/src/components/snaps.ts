/**
 * Bottom sheets on a phone (TM05-103): the three heights a panel snaps to, and which one a
 * drag ends nearest. Pure, so node --test checks it.
 */

export type Snap = "peek" | "half" | "full";
export const SNAPS: readonly Snap[] = ["peek", "half", "full"];

/** Below this width the side panels become bottom sheets. Mirrored in the CSS. */
export const PHONE_MAX_WIDTH = 640;
export const PHONE_QUERY = `(max-width: ${PHONE_MAX_WIDTH}px)`;

/**
 * Pixel heights for a map area `available` px tall: peek shows the panel's header and a
 * line under it; half is half the map; full leaves a strip of map at the top so the sheet
 * still reads as a sheet.
 */
export function snapHeights(available: number, peek = 132, topGap = 56): Record<Snap, number> {
  const full = Math.max(peek, available - topGap);
  return { peek: Math.min(peek, full), half: Math.max(peek, Math.round(available / 2)), full };
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
