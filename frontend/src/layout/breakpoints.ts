/**
 * The app's one set of layout breakpoints (TM05-130). Pure, so node --test checks it.
 *
 *   phone    0 – 640 px     side panels become bottom sheets (components/Sheet.tsx)
 *   tablet   641 – 1279 px  tablets, and large phones in landscape: panels stay docked,
 *                           sized down, under the search row (tablet.css)
 *   desktop  1280 px and up the original layout, unchanged
 *
 * CSS cannot read a custom property inside `@media`, so stylesheets spell these queries
 * out, and tests/breakpoints.test.ts fails the build if any `@media` width in src/ is not
 * one of the MEDIA strings below, character for character. TypeScript imports MEDIA.
 */

export type Layout = "phone" | "tablet" | "desktop";

/** The widest viewport, in CSS px, that each layout covers. Desktop has no upper bound. */
export const BREAKPOINTS = {
  phoneMaxPx: 640,
  tabletMaxPx: 1279,
} as const;

/** The only width media queries the app uses, in CSS and in matchMedia(). */
export const MEDIA = {
  phone: `(max-width: ${BREAKPOINTS.phoneMaxPx}px)`,
  tablet: `(min-width: ${BREAKPOINTS.phoneMaxPx + 1}px) and (max-width: ${BREAKPOINTS.tabletMaxPx}px)`,
  /** Phone or tablet: anything narrower than the desktop layout. */
  belowDesktop: `(max-width: ${BREAKPOINTS.tabletMaxPx}px)`,
} as const;

/** The layout a viewport `widthPx` wide gets. */
export function layoutFor(widthPx: number): Layout {
  if (widthPx <= BREAKPOINTS.phoneMaxPx) return "phone";
  if (widthPx <= BREAKPOINTS.tabletMaxPx) return "tablet";
  return "desktop";
}
