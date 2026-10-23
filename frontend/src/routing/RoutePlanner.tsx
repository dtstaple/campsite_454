/**
 * Plan a route across connected trails (TM05-119).
 *
 * "Plan a route" arms the map: each click adds a stop, the first the start and the last
 * the end. "Route" asks the API for the quickest (Naismith) or shortest way through them,
 * in order, and hands the answer to the trail panel, where Find campsites, + Night and
 * the GPX work as they do for any trail. Once routed, the planner folds to one button,
 * keeping its stops, so the map and the trail panel (a sheet on a phone) have the room.
 *
 * While picking, the shared placement flag (waypoints/placement.ts) is set, so the click
 * neither opens a trail nor a popup.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import { planRoute, RouteApiError, type RouteDetail } from "../trails/api";
import { placement } from "../waypoints/placement";
import { COSTS, stopLabels, withoutStop, withSuggestion, type Cost, type RouteSuggestion } from "./planned";
import "./routing.css";

interface Props {
  map: maplibregl.Map | null;
  withinM: number;
  /** The route is back: open it in the trail panel. */
  onPlanned: (detail: RouteDetail) => void;
}

export default function RoutePlanner({ map, withinM, onPlanned }: Props) {
  const [open, setOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const [stops, setStops] = useState<[number, number][]>([]);
  const [cost, setCost] = useState<Cost>("naismith");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<RouteSuggestion | null>(null);

  // --- picking stops on the map ----------------------------------------------------------
  useEffect(() => {
    if (!map || !picking) return;
    placement.active = true;
    const container = map.getContainer();
    container.classList.add("is-picking-route-stops");
    const onClick = (event: maplibregl.MapMouseEvent) => {
      setError(null);
      setStops((current) => [
        ...current,
        [Number(event.lngLat.lng.toFixed(6)), Number(event.lngLat.lat.toFixed(6))],
      ]);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPicking(false);
    };
    map.on("click", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      map.off("click", onClick);
      window.removeEventListener("keydown", onKey);
      container.classList.remove("is-picking-route-stops");
      // After the last click has reached the other handlers, which check the flag.
      window.setTimeout(() => {
        placement.active = false;
      }, 0);
    };
  }, [map, picking]);

  // --- the stops' markers ------------------------------------------------------------------
  useEffect(() => {
    if (!map || !open) return;
    const labels = stopLabels(stops.length);
    const markers = stops.map((stop, i) => {
      const element = document.createElement("div");
      element.className = "route-stop-marker";
      element.textContent = labels[i] === "Start" ? "S" : labels[i] === "End" ? "E" : String(i);
      element.setAttribute("aria-hidden", "true");
      return new maplibregl.Marker({ element, anchor: "center" }).setLngLat(stop).addTo(map);
    });
    return () => markers.forEach((marker) => marker.remove());
  }, [map, open, stops]);

  const abort = useRef<AbortController | null>(null);
  const route = useCallback(async () => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true);
    setError(null);
    setSuggestion(null);
    try {
      const detail = await planRoute(stops, cost, withinM, controller.signal);
      setPicking(false);
      setOpen(false);
      onPlanned(detail);
    } catch (cause) {
      if (controller.signal.aborted) return;
      setError(cause instanceof RouteApiError ? cause.message : String(cause));
      setSuggestion(cause instanceof RouteApiError ? cause.suggestion : null);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }, [stops, cost, withinM, onPlanned]);

  const close = () => {
    abort.current?.abort();
    setPicking(false);
    setOpen(false);
    setBusy(false);
    setError(null);
    setStops([]);
  };

  if (!open) {
    return (
      <div className="route-planner is-closed">
        <button
          type="button"
          className="route-planner-cost"
          onClick={() => {
            setOpen(true);
            setPicking(stops.length === 0);
          }}
        >
          {stops.length > 0 ? "Edit route" : "Plan a route"}
        </button>
      </div>
    );
  }

  const labels = stopLabels(stops.length);
  return (
    <section className="route-planner" aria-label="Plan a route">
      <div className="route-planner-head">
        <h2 className="route-planner-title">Plan a route</h2>
        <button type="button" className="link-button" onClick={close}>
          Close
        </button>
      </div>
      <p className="route-planner-hint">
        {picking
          ? stops.length < 2
            ? "Click the map near a trail for the start, then the end. Stops in between are visited in order."
            : "Click to add more stops, or route it."
          : "Add stops to change the route."}
      </p>
      {stops.length > 0 && (
        <p className="route-planner-count">
          {stops.length === 1 ? "Start picked" : `${stops.length} stops: start, ${stops.length > 2 ? `${stops.length - 2} between, ` : ""}end`}
          {" · "}
          <button type="button" className="link-button" onClick={() => setStops(stops.slice(0, -1))}>
            Undo last
          </button>
        </p>
      )}
      {stops.length > 0 && (
        <ol className="route-planner-stops">
          {stops.map((stop, i) => (
            <li key={`${stop[0]},${stop[1]},${i}`} className="route-planner-stop">
              <span className="route-planner-stop-label">
                {labels[i]}: {stop[1].toFixed(4)}, {stop[0].toFixed(4)}
              </span>
              <button
                type="button"
                className="link-button"
                aria-label={`Remove ${labels[i]}`}
                onClick={() => setStops(withoutStop(stops, i))}
              >
                Remove
              </button>
            </li>
          ))}
        </ol>
      )}
      <div className="route-planner-costs" role="group" aria-label="Route by">
        {COSTS.map((option) => (
          <button
            key={option.id}
            type="button"
            className="route-planner-cost"
            aria-pressed={cost === option.id}
            title={option.hint}
            onClick={() => setCost(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <div className="route-planner-actions">
        <button
          type="button"
          className="route-planner-cost"
          aria-pressed={picking}
          onClick={() => setPicking(!picking)}
        >
          {picking ? "Stop adding" : "Add stops"}
        </button>
        <button
          type="button"
          className="button-primary"
          disabled={stops.length < 2 || busy}
          onClick={route}
        >
          {busy ? "Routing…" : "Route"}
        </button>
      </div>
      {stops.length > 0 && (
        <div className="route-planner-actions">
          <button type="button" className="link-button" onClick={() => setStops([])}>
            Clear stops
          </button>
        </div>
      )}
      {error && (
        <p className="route-planner-error" role="alert">
          {error}
        </p>
      )}
      {suggestion && (
        <div className="route-planner-actions">
          <button
            type="button"
            className="route-planner-cost"
            onClick={() => {
              setStops(withSuggestion(stops, suggestion));
              setSuggestion(null);
              setError(null);
            }}
          >
            {suggestion.instead_of === "start" ? "Start" : "End"} on {suggestion.trail_name} instead
          </button>
        </div>
      )}
    </section>
  );
}
