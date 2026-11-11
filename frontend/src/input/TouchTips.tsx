/**
 * Tooltips for a finger (TM05-131). On a desktop a `title` shows on hover; a touch screen
 * has no hover, so a tap on anything with a title (that is not itself a control: see
 * tipFor in touch.ts) shows the same text in a bubble beside it, and outlines what was
 * tapped. The next tap elsewhere, a scroll or a resize puts it away. Mouse and pen events
 * are ignored, so a desktop still gets the browser's own tooltip and nothing else.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { isTouch, placeTip, tipFor, type Box, type TipNode } from "./touch";

const INTERACTIVE = "button, a[href], input, select, textarea, summary, label, [role='button']";
const OPEN_CLASS = "is-tip-open";

function titleOf(el: Element): string | null {
  const attr = el.getAttribute("title");
  if (attr) return attr;
  const svgTitle = el instanceof SVGElement ? el.querySelector(":scope > title") : null;
  return svgTitle?.textContent ?? null;
}

function chainFrom(start: Element | null): Element[] {
  const chain: Element[] = [];
  for (let el = start; el && el !== document.body; el = el.parentElement) chain.push(el);
  return chain;
}

function describe(el: Element): TipNode {
  return {
    title: titleOf(el),
    interactive: el.matches(INTERACTIVE),
    disabled: (el as HTMLButtonElement).disabled === true || el.getAttribute("aria-disabled") === "true",
  };
}

interface Tip {
  text: string;
  anchor: Box;
}

export default function TouchTips() {
  const [tip, setTip] = useState<Tip | null>(null);
  const opened = useRef<Element | null>(null);
  const bubble = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => {
    const close = () => {
      opened.current?.classList.remove(OPEN_CLASS);
      opened.current = null;
      setTip(null);
    };
    const onPointerUp = (event: PointerEvent) => {
      if (!isTouch(event.pointerType)) return;
      // From the point, not event.target: a control holding pointer capture (the elevation
      // profile) would otherwise hide what is under the finger.
      const chain = chainFrom(document.elementFromPoint(event.clientX, event.clientY));
      const index = tipFor(chain.map(describe));
      if (index < 0) return close();
      const el = chain[index];
      if (el === opened.current) return close(); // a second tap puts it away
      close();
      el.classList.add(OPEN_CLASS);
      opened.current = el;
      const rect = el.getBoundingClientRect();
      setTip({
        text: titleOf(el) ?? "",
        anchor: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
      });
    };
    document.addEventListener("pointerup", onPointerUp, true);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerup", onPointerUp, true);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      close();
    };
  }, []);

  // Measure the bubble once it renders, then place it beside its anchor.
  useLayoutEffect(() => {
    if (!tip || !bubble.current) return setPlace(null);
    const { width, height } = bubble.current.getBoundingClientRect();
    setPlace(placeTip(tip.anchor, { width, height }, { width: document.documentElement.clientWidth, height: document.documentElement.clientHeight }));
  }, [tip]);

  if (!tip) return null;
  return createPortal(
    <div
      ref={bubble}
      className="touch-tip"
      role="tooltip"
      style={place ? { left: place.left, top: place.top } : { visibility: "hidden" }}
    >
      {tip.text}
    </div>,
    document.body,
  );
}
