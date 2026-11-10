/**
 * A side panel that becomes a draggable bottom sheet on a phone (TM05-103).
 *
 * Above the phone breakpoint (layout/breakpoints.ts) it is the plain <aside> it always was. Below it, it gains a handle
 * on its top edge and snaps between three heights (snaps.ts): peek (the header and a line),
 * half, and full. Drag the handle to resize, flick to move one step, or tap it to step
 * through the sizes. The sheet's current height is published as --sheet-height on the map
 * page, so map controls can sit above it.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { MEDIA } from "../layout/breakpoints";
import { nearestSnap, nextSnap, snapHeights, type Snap } from "./snaps";
import "./sheet.css";

function usePhone(): boolean {
  const [phone, setPhone] = useState(
    () => typeof window !== "undefined" && window.matchMedia(MEDIA.phone).matches,
  );
  useEffect(() => {
    const query = window.matchMedia(MEDIA.phone);
    const onChange = () => setPhone(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return phone;
}

/** A drag shorter than this, if fast, is a flick: one step, whatever the distance. */
const FLICK_MAX_PX = 120;

interface Props {
  className: string;
  label: string;
  children: ReactNode;
  /** Where the sheet starts on a phone. */
  initial?: Snap;
}

export default function Sheet({ className, label, children, initial = "half" }: Props) {
  const phone = usePhone();
  const ref = useRef<HTMLElement>(null);
  const [snap, setSnap] = useState<Snap>(initial);
  const [dragHeight, setDragHeight] = useState<number | null>(null);
  const drag = useRef<{ startY: number; startHeight: number; lastY: number; lastT: number; velocity: number } | null>(null);

  // The map area's height, re-measured on rotation and as Safari's bars show and hide: the
  // shell is 100dvh (App.css), so the map area resizes with the visible screen and the
  // ResizeObserver sees it; visualViewport covers a browser that resizes without reflow.
  const [available, setAvailable] = useState(() =>
    typeof window !== "undefined" ? window.innerHeight : 800,
  );
  useEffect(() => {
    const host = ref.current?.parentElement;
    if (!host) return;
    const measure = () => setAvailable(host.clientHeight);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(host);
    window.visualViewport?.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.visualViewport?.removeEventListener("resize", measure);
    };
  }, []);
  const heights = () => snapHeights(available);

  // Publish the height for the map controls (sheet.css), and clear it when the sheet goes.
  const height = phone ? (dragHeight ?? heights()[snap]) : null;
  useEffect(() => {
    const host = ref.current?.parentElement;
    if (!host || height === null) return;
    host.style.setProperty("--sheet-height", `${height}px`);
    return () => {
      host.style.removeProperty("--sheet-height");
    };
  }, [height]);

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    const now = performance.now();
    drag.current = { startY: event.clientY, startHeight: heights()[snap], lastY: event.clientY, lastT: now, velocity: 0 };
  };
  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state) return;
    const now = performance.now();
    state.velocity = (event.clientY - state.lastY) / Math.max(now - state.lastT, 1);
    state.lastY = event.clientY;
    state.lastT = now;
    const limits = heights();
    const next = state.startHeight - (event.clientY - state.startY);
    setDragHeight(Math.min(limits.full, Math.max(limits.peek * 0.6, next)));
  };
  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    drag.current = null;
    if (!state) return;
    const moved = Math.abs(event.clientY - state.startY);
    if (moved < 6) {
      setSnap((current) => nextSnap(current)); // a tap
    } else {
      // A short, fast flick moves one step; a long drag settles where it was let go.
      const flick = moved < FLICK_MAX_PX ? state.velocity : 0;
      setSnap(nearestSnap(dragHeight ?? state.startHeight, heights(), flick, snap));
    }
    setDragHeight(null);
  };

  return (
    <aside
      ref={ref}
      className={`${className}${phone ? ` sheet is-${snap}${dragHeight !== null ? " is-dragging" : ""}` : ""}`}
      aria-label={label}
      style={height !== null ? { height } : undefined}
    >
      {phone && (
        <div
          className="sheet-handle"
          role="button"
          tabIndex={0}
          aria-label={`Resize panel (now ${snap})`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => {
            drag.current = null;
            setDragHeight(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              setSnap((current) => nextSnap(current));
            }
          }}
        >
          <span aria-hidden="true" />
        </div>
      )}
      {children}
    </aside>
  );
}
