/**
 * Live location (TM05-103): a GPS dot with its accuracy circle, and "Follow me", which
 * keeps the map centred on the hiker while they walk.
 *
 *   ◎  turns live location on (asking the browser if it hasn't been allowed) and off.
 *   ➤  Follow me: on, every new fix re-centres the map; dragging the map turns it off.
 *
 * Positions come from navigator.geolocation.watchPosition with high accuracy, and are
 * passed up (onPosition) so the trail panel can say "mi X.X along <trail>". Nothing leaves
 * the browser. Replaces TM05-78's MapLibre locate button: one location control, not two.
 */

import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import { prefersReducedMotion } from "../trails/terrain3d";
import { token } from "../theme";
import { accuracyCircle } from "./live";
import { forgetDenial } from "./locate";
import "./location.css";

export interface LivePosition {
  lon: number;
  lat: number;
  accuracyM: number;
}

interface Props {
  map: maplibregl.Map | null;
  onPosition: (position: LivePosition | null) => void;
}

const SOURCE = "live-accuracy";
const FILL = "live-accuracy-fill";
const LINE = "live-accuracy-line";
const FOLLOW_ZOOM = 15;

function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export default function LiveLocation({ map, onPosition }: Props) {
  const [on, setOn] = useState(false);
  const [follow, setFollow] = useState(false);
  const [position, setPosition] = useState<LivePosition | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const report = useRef(onPosition);
  useEffect(() => {
    report.current = onPosition;
  }, [onPosition]);

  // --- watching ------------------------------------------------------------------------------
  useEffect(() => {
    if (!on) return;
    if (!("geolocation" in navigator)) {
      queueMicrotask(() => {
        setProblem("Location isn't available here (it needs HTTPS).");
        setOn(false);
      });
      return;
    }
    const id = navigator.geolocation.watchPosition(
      ({ coords }) => {
        forgetDenial(safeStorage());
        setProblem(null);
        const next = { lon: coords.longitude, lat: coords.latitude, accuracyM: coords.accuracy };
        setPosition(next);
        report.current(next);
      },
      (error) => {
        setProblem(
          error.code === 1
            ? "Location is blocked for this site. Allow it in the browser's settings."
            : "Couldn't get a GPS fix yet.",
        );
        if (error.code === 1) setOn(false);
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 30_000 },
    );
    return () => {
      navigator.geolocation.clearWatch(id);
      setPosition(null);
      report.current(null);
    };
  }, [on]);

  // --- the dot and the accuracy circle -----------------------------------------------------------
  useEffect(() => {
    if (!map || !position) return;
    const element = document.createElement("div");
    element.className = "live-dot";
    element.setAttribute("aria-label", "You are here");
    const marker = new maplibregl.Marker({ element }).setLngLat([position.lon, position.lat]).addTo(map);
    const circle: GeoJSON.Feature = {
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [accuracyCircle([position.lon, position.lat], position.accuracyM)] },
    };
    const source = map.getSource(SOURCE) as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(circle);
    } else if (map.isStyleLoaded()) {
      map.addSource(SOURCE, { type: "geojson", data: circle });
      map.addLayer({ id: FILL, type: "fill", source: SOURCE, paint: { "fill-color": token("--live-accuracy-fill") } });
      map.addLayer({
        id: LINE,
        type: "line",
        source: SOURCE,
        paint: { "line-color": token("--live-accuracy-line"), "line-width": 1 },
      });
    }
    map.getContainer().classList.add("is-live-location");
    return () => {
      marker.remove();
    };
  }, [map, position]);

  useEffect(() => {
    if (!map || on) return;
    (map.getSource(SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: [],
    });
    map.getContainer().classList.remove("is-live-location");
  }, [map, on]);

  // --- follow me -------------------------------------------------------------------------------
  useEffect(() => {
    if (!map || !follow || !position) return;
    map.easeTo({
      center: [position.lon, position.lat],
      zoom: Math.max(map.getZoom(), FOLLOW_ZOOM),
      duration: prefersReducedMotion() ? 0 : 600,
    });
  }, [map, follow, position]);

  useEffect(() => {
    if (!map || !follow) return;
    // The hiker panning to look ahead means "stop following", as in every map app.
    const stop = (event: { originalEvent?: unknown }) => {
      if (event.originalEvent) setFollow(false);
    };
    map.on("dragstart", stop);
    return () => {
      map.off("dragstart", stop);
    };
  }, [map, follow]);

  return (
    <div className="live-controls" role="group" aria-label="Your location">
      <button
        type="button"
        className={`live-button${on ? " is-active" : ""}`}
        aria-pressed={on}
        title={on ? "Stop showing your location" : "Show your location"}
        onClick={() => {
          setOn((value) => !value);
          setFollow((value) => (on ? false : value));
        }}
      >
        <span aria-hidden="true">◎</span>
        <span className="live-label">{on ? (position ? `±${Math.round(position.accuracyM)} m` : "Locating…") : "Location"}</span>
      </button>
      <button
        type="button"
        className={`live-button${follow ? " is-active" : ""}`}
        aria-pressed={follow}
        title="Keep the map centred on you"
        onClick={() => {
          if (!on) setOn(true);
          setFollow((value) => !value);
        }}
      >
        <span aria-hidden="true">➤</span>
        <span className="live-label">Follow me</span>
      </button>
      {problem && (
        <div className="live-problem" role="status">
          {problem}
        </div>
      )}
    </div>
  );
}
