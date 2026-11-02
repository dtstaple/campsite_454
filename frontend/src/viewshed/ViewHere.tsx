/**
 * "What can I see from here?" (TM05-151) for any point on the map.
 *
 * Right-click on a desktop, or long-press on a phone, offers the one action in a small
 * popup at that point. Choosing it asks /api/viewshed/ for what the terrain lets you see
 * from there (computed on the server, a few seconds the first time, cached after), draws
 * the visible ground, and shows a short summary in a card with the bare-earth caveat.
 *
 * While a waypoint or route stop is being placed (waypoints/placement.ts), presses are
 * left alone. The overlay has its own source (terrain/zonesLayer.ts), so a campsite's
 * "Show what I can see" and this one never clear each other.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import * as maplibregl from "maplibre-gl";
import type { Feature } from "geojson";
import { API_BASE_URL } from "../api";
import { POINT_VIEWSHED_SOURCE, showViewshed } from "../terrain/zonesLayer";
import { placement } from "../waypoints/placement";
import {
  fetchPointViewshed,
  LONG_PRESS_MS,
  LongPress,
  MENU_LABEL,
  placeLabel,
  ViewshedError,
  type PointViewshed,
} from "./here";
import "./viewshed.css";

interface Props {
  map: maplibregl.Map | null;
}

type Place = { lng: number; lat: number };

type ViewState =
  | { status: "idle" }
  | { status: "loading"; place: Place }
  | { status: "ready"; place: Place; feature: PointViewshed }
  | { status: "error"; place: Place; message: string };

export default function ViewHere({ map }: Props) {
  const [menu, setMenu] = useState<{ place: Place; slot: HTMLElement } | null>(null);
  const [view, setView] = useState<ViewState>({ status: "idle" });
  const abort = useRef<AbortController | null>(null);

  // --- right-click and long-press open the menu -------------------------------------------
  useEffect(() => {
    if (!map) return;
    let popup: maplibregl.Popup | null = null;
    const open = (lngLat: maplibregl.LngLat) => {
      if (placement.active) return;
      popup?.remove();
      const slot = document.createElement("div");
      popup = new maplibregl.Popup({ closeButton: true, className: "viewshed-menu" })
        .setLngLat(lngLat)
        .setDOMContent(slot)
        .addTo(map);
      popup.on("close", () => setMenu((current) => (current?.slot === slot ? null : current)));
      setMenu({ place: { lng: lngLat.lng, lat: lngLat.lat }, slot });
    };

    const onContextMenu = (event: maplibregl.MapMouseEvent) => {
      event.preventDefault();
      open(event.lngLat);
    };

    // Long press. Android also fires contextmenu for one; opening twice at the same point
    // just replaces the popup.
    const press = new LongPress();
    let timer: number | undefined;
    let pressedAt: maplibregl.LngLat | null = null;
    const clear = () => {
      press.cancel();
      window.clearTimeout(timer);
    };
    const onTouchStart = (event: maplibregl.MapTouchEvent) => {
      const touches = event.originalEvent.touches.length;
      press.start(event.point.x, event.point.y, performance.now(), touches);
      pressedAt = event.lngLat;
      window.clearTimeout(timer);
      if (touches !== 1) return;
      timer = window.setTimeout(() => {
        if (press.due(performance.now()) && pressedAt) open(pressedAt);
      }, LONG_PRESS_MS);
    };
    const onTouchMove = (event: maplibregl.MapTouchEvent) =>
      press.move(event.point.x, event.point.y, event.originalEvent.touches.length);

    map.on("contextmenu", onContextMenu);
    map.on("touchstart", onTouchStart);
    map.on("touchmove", onTouchMove);
    map.on("touchend", clear);
    map.on("touchcancel", clear);
    map.on("dragstart", clear);
    return () => {
      clear();
      popup?.remove();
      map.off("contextmenu", onContextMenu);
      map.off("touchstart", onTouchStart);
      map.off("touchmove", onTouchMove);
      map.off("touchend", clear);
      map.off("touchcancel", clear);
      map.off("dragstart", clear);
    };
  }, [map]);

  // --- asking the server ------------------------------------------------------------------
  const look = useCallback((place: Place) => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setView({ status: "loading", place });
    fetchPointViewshed(API_BASE_URL, place.lat, place.lng, controller.signal)
      .then((feature) => {
        if (!controller.signal.aborted) setView({ status: "ready", place, feature });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        const message = error instanceof ViewshedError ? error.message : String(error);
        setView({ status: "error", place, message });
      });
  }, []);

  const close = useCallback(() => {
    abort.current?.abort();
    setView({ status: "idle" });
  }, []);

  // --- the overlay and the observer's marker ----------------------------------------------
  useEffect(() => {
    if (!map) return;
    // A view with nothing visible has no geometry: the card says so, nothing to draw.
    const drawn = view.status === "ready" && view.feature.geometry ? (view.feature as Feature) : null;
    showViewshed(map, drawn, POINT_VIEWSHED_SOURCE);
    if (view.status === "idle") return;
    const element = document.createElement("div");
    element.className = "viewshed-observer";
    element.setAttribute("aria-hidden", "true");
    const marker = new maplibregl.Marker({ element, anchor: "center" })
      .setLngLat([view.place.lng, view.place.lat])
      .addTo(map);
    return () => {
      marker.remove();
    };
  }, [map, view]);

  useEffect(() => () => abort.current?.abort(), []);

  useEffect(() => {
    if (view.status === "idle") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view.status, close]);

  return (
    <>
      {menu &&
        createPortal(
          <button
            type="button"
            className="viewshed-menu-action"
            onClick={() => {
              const place = menu.place;
              setMenu(null);
              look(place);
            }}
          >
            {MENU_LABEL}
          </button>,
          menu.slot,
        )}
      {view.status !== "idle" && <ViewCard view={view} onRetry={look} onClose={close} />}
    </>
  );
}

function ViewCard({
  view,
  onRetry,
  onClose,
}: {
  view: Exclude<ViewState, { status: "idle" }>;
  onRetry: (place: Place) => void;
  onClose: () => void;
}) {
  return (
    <section
      className={`viewshed-here is-${view.status}`}
      aria-label="What you can see from here"
      aria-busy={view.status === "loading"}
    >
      <header className="viewshed-here-head">
        <h2 className="viewshed-here-title">What you can see from here</h2>
        <button type="button" className="viewshed-here-close" onClick={onClose} aria-label="Close view">
          ×
        </button>
      </header>
      <div className="viewshed-here-place">{placeLabel(view.place.lat, view.place.lng)}</div>

      {view.status === "loading" && (
        <div className="viewshed-here-status" role="status">
          <span className="spinner" aria-hidden="true" />
          Working out what the terrain lets you see… this can take a few seconds.
        </div>
      )}

      {view.status === "error" && (
        <div role="alert">
          <p className="viewshed-here-error">{view.message}</p>
          <button type="button" className="viewshed-here-action" onClick={() => onRetry(view.place)}>
            Try again
          </button>
        </div>
      )}

      {view.status === "ready" && (
        <div role="status">
          <p className="viewshed-here-summary">{view.feature.properties.summary}</p>
          <p className="viewshed-here-caveat">
            <span className="viewshed-here-label">{view.feature.properties.label}</span>
            {view.feature.properties.note}
          </p>
        </div>
      )}
    </section>
  );
}
