/**
 * Keeps the field being typed in visible while the on-screen keyboard is open (TM05-133).
 *
 * Mounted once, in App. While a keyboard covers the bottom of the page it publishes
 * --keyboard-inset (the px it covers) and --keyboard-visible-height on <html> and adds the
 * `keyboard-open` class, so phone.css can lift a bottom sheet or the waypoint editor onto
 * the keyboard instead of leaving them under it. Then it scrolls the focused field into
 * the part of each scroll container that is still visible.
 *
 * On a desktop no keyboard ever covers the page, so none of this switches on.
 */

import { useEffect } from "react";
import { isTextEntry, keyboardInset, revealDelta } from "./keyboard";

/** The nearest ancestor of `element` that scrolls vertically and has something to scroll. */
function scrollParent(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node; node = node.parentElement) {
    const { overflowY } = getComputedStyle(node);
    if ((overflowY === "auto" || overflowY === "scroll") && node.scrollHeight > node.clientHeight) {
      return node;
    }
  }
  return null;
}

export function useKeyboard(): void {
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const root = document.documentElement;
    let frame = 0;

    const reveal = () => {
      const field = document.activeElement;
      if (!(field instanceof HTMLElement) || !isTextEntry(field)) return;
      // Bounding rects and the visual viewport's offsetTop share layout coordinates.
      const visibleTop = viewport.offsetTop;
      const visibleBottom = viewport.offsetTop + viewport.height;
      // Innermost container first (the sheet or list the field is in), then outwards.
      for (let box = scrollParent(field); box; box = scrollParent(box)) {
        const rect = box.getBoundingClientRect();
        const delta = revealDelta(field.getBoundingClientRect(), {
          top: Math.max(rect.top, visibleTop),
          bottom: Math.min(rect.bottom, visibleBottom),
        });
        if (delta) box.scrollTop += delta;
      }
    };

    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const inset = keyboardInset(window.innerHeight, viewport);
        root.style.setProperty("--keyboard-inset", `${inset}px`);
        root.style.setProperty("--keyboard-visible-height", `${Math.round(viewport.height)}px`);
        root.classList.toggle("keyboard-open", inset > 0);
        // One more frame, so the lifted sheet has laid out before measuring the field.
        if (inset > 0) frame = requestAnimationFrame(reveal);
      });
    };
    const onFocusIn = (event: FocusEvent) => {
      if (event.target instanceof HTMLElement && isTextEntry(event.target)) update();
    };

    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    document.addEventListener("focusin", onFocusIn);
    update();
    return () => {
      cancelAnimationFrame(frame);
      viewport.removeEventListener("resize", update);
      viewport.removeEventListener("scroll", update);
      document.removeEventListener("focusin", onFocusIn);
      root.classList.remove("keyboard-open");
      root.style.removeProperty("--keyboard-inset");
      root.style.removeProperty("--keyboard-visible-height");
    };
  }, []);
}
