/**
 * Nothing hidden behind hover (TM05-131). Pure, so node --test checks it.
 *
 * A mouse can point at something without pressing it, and the desktop uses that: hovering
 * a connecting trail shows where it joins, hovering the profile moves a cursor along it, a
 * `title` explains a number. A finger cannot point without pressing, so on a touch screen:
 *
 *   - a tap shows what a hover would, and the thing tapped stays highlighted until the
 *     next tap elsewhere;
 *   - where a tap would also *go* somewhere (open the connecting trail), the first tap
 *     previews and a second tap on the same thing goes;
 *   - a mouse (or a pen hovering) keeps the desktop behaviour exactly.
 */

/** PointerEvent.pointerType: "mouse", "pen" or "touch" ("" in a few old browsers). */
export function isTouch(pointerType: string): boolean {
  return pointerType === "touch";
}

/**
 * A tap or click on a previewable item `id`, while `pinned` is the item a touch last
 * previewed. A mouse click always opens (its hover already previewed); a first touch
 * pins the preview; a second touch on the same item opens it.
 */
export function tapPreview(
  pinned: string | null,
  id: string,
  pointerType: string,
): { pinned: string | null; open: boolean } {
  if (!isTouch(pointerType)) return { pinned, open: true };
  if (pinned === id) return { pinned: id, open: true };
  return { pinned: id, open: false };
}

/** Whether a pointer leaving the profile clears its cursor: a mouse yes, a lifted finger no. */
export function clearsOnLeave(pointerType: string, dragging: boolean): boolean {
  return !dragging && !isTouch(pointerType);
}

/** One element from a tap's target up through its ancestors, as tipFor() needs it. */
export interface TipNode {
  /** Its `title` attribute, or an SVG element's <title> child. */
  title: string | null;
  /** A button, link, field or label: a tap on it does something. */
  interactive: boolean;
  disabled: boolean;
}

/**
 * Which element's tooltip a touch tap shows: the index into `chain` (the tapped element
 * first, then its ancestors), or -1 for none. An enabled control's tap does what the
 * control does, so neither it nor anything inside it pops a tip; a disabled control says
 * why it is disabled.
 */
export function tipFor(chain: readonly TipNode[]): number {
  if (chain.some((node) => node.interactive && !node.disabled)) return -1;
  return chain.findIndex((node) => Boolean(node.title?.trim()));
}

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Where the tip bubble goes: centred above the tapped element, or below it when there is
 * no room above, and always `margin` px inside the viewport.
 */
export function placeTip(
  anchor: Box,
  tip: { width: number; height: number },
  viewport: { width: number; height: number },
  gap = 8,
  margin = 8,
): { left: number; top: number; below: boolean } {
  const centred = anchor.left + anchor.width / 2 - tip.width / 2;
  const maxLeft = Math.max(margin, viewport.width - margin - tip.width);
  const left = Math.min(Math.max(centred, margin), maxLeft);
  const above = anchor.top - gap - tip.height;
  const below = above < margin;
  const top = below
    ? Math.min(anchor.top + anchor.height + gap, viewport.height - margin - tip.height)
    : above;
  return { left: Math.round(left), top: Math.round(top), below };
}
