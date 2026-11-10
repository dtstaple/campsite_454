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
  /** The tallest viewport counted as short (a phone in landscape is 320-430px). */
  shortMaxPx: 500,
} as const;

/** The only width and height media queries the app uses, in CSS and in matchMedia(). */
export const MEDIA = {
  phone: `(max-width: ${BREAKPOINTS.phoneMaxPx}px)`,
  tablet: `(min-width: ${BREAKPOINTS.phoneMaxPx + 1}px) and (max-width: ${BREAKPOINTS.tabletMaxPx}px)`,
  /** Phone or tablet: anything narrower than the desktop layout. */
  belowDesktop: `(max-width: ${BREAKPOINTS.tabletMaxPx}px)`,
  /** A short viewport: a phone on its side. Overlays that open tall start folded. */
  short: `(max-height: ${BREAKPOINTS.shortMaxPx}px)`,
} as const;

/**
 * Overlays that list a lot start folded where the map is small (matchMedia queries): the
 * layer list below desktop width, the search results on a phone or a phone on its side.
 */
export const FOLDED_AT_START = {
  layers: MEDIA.belowDesktop,
  searchResults: `${MEDIA.phone}, ${MEDIA.short}`,
} as const;

/** The layout a viewport `widthPx` wide gets. */
export function layoutFor(widthPx: number): Layout {
  if (widthPx <= BREAKPOINTS.phoneMaxPx) return "phone";
  if (widthPx <= BREAKPOINTS.tabletMaxPx) return "tablet";
  return "desktop";
}
