/**
 * The on-screen keyboard (TM05-133): how much of the layout it covers, which elements
 * bring it up, and how far a scroll container has to move to keep the focused field in
 * view. Pure, so node --test checks it; useKeyboard.ts wires it to the page.
 *
 * Browsers report the keyboard through the visual viewport: it shrinks to the part of the
 * page left visible above the keyboard (Android Chrome, iOS Safari), and on iOS it can
 * also pan down the layout (offsetTop). Whatever of the layout lies below the visible part
 * is under the keyboard.
 */

/** Less than this is the browser's own toolbar collapsing or growing, not a keyboard. */
export const KEYBOARD_MIN_PX = 120;

/** Room kept between a revealed field and the edge of what is visible. */
export const REVEAL_MARGIN_PX = 12;

export interface VisualViewportLike {
  height: number;
  offsetTop: number;
}

/**
 * Pixels at the bottom of a `layoutHeight` px layout hidden by the keyboard, or 0 when no
 * keyboard is open (or the browser has no visual viewport to tell).
 */
export function keyboardInset(layoutHeight: number, viewport: VisualViewportLike | null): number {
  if (!viewport) return 0;
  const covered = Math.round(layoutHeight - viewport.offsetTop - viewport.height);
  return covered >= KEYBOARD_MIN_PX ? covered : 0;
}

/** Input types that type text, and so open the keyboard. */
const TEXT_INPUT_TYPES = new Set([
  "",
  "text",
  "search",
  "email",
  "number",
  "password",
  "tel",
  "url",
]);

export interface ElementLike {
  tagName: string;
  type?: string;
  readOnly?: boolean;
  isContentEditable?: boolean;
}

/** True when focusing `element` brings up the on-screen keyboard. */
export function isTextEntry(element: ElementLike | null): boolean {
  if (!element) return false;
  if (element.isContentEditable) return true;
  if (element.readOnly) return false;
  const tag = element.tagName.toLowerCase();
  if (tag === "textarea") return true;
  return tag === "input" && TEXT_INPUT_TYPES.has((element.type ?? "").toLowerCase());
}

export interface Span {
  top: number;
  bottom: number;
}

/**
 * How far to scroll (px, positive scrolls down) so `field` sits inside `visible` with
 * `margin` to spare. Zero when it already does. A field taller than the visible span is
 * aligned by its top, where the caret starts.
 */
export function revealDelta(field: Span, visible: Span, margin = REVEAL_MARGIN_PX): number {
  const top = visible.top + margin;
  const bottom = visible.bottom - margin;
  if (field.top < top) return field.top - top;
  if (field.bottom > bottom) return Math.min(field.bottom - bottom, field.top - top);
  return 0;
}
