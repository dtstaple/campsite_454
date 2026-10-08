/**
 * Opens the map where the user is (TM05-78). Renders the "outside coverage" notice; the
 * rest happens on the map: a camera move and a dot where the user is. Asking again, live
 * tracking and follow mode are LiveLocation.tsx (TM05-103). The decisions are in locate.ts.
 *
 * The map opens on the default region straight away and moves only when an answer comes
 * back -- and not at all if the user has already started panning or zooming by then.
 */

import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import { REGIONS, type Region } from "../regions";
import { prefersReducedMotion } from "../trails/terrain3d";
import {
  LOCATED_ZOOM,
  aboutKm,
  locateStart,
  type StartOutcome,
} from "./locate";
import "./location.css";

interface Props {
  map: maplibregl.Map | null;
  onRegion: (region: Region) => void;
}

function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export default function StartLocation({ map, onRegion }: Props) {
  const [outside, setOutside] = useState<Extract<StartOutcome, { kind: "outside" }> | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!map || started.current) return;
    started.current = true;

    // Asking again on demand is the live-location control's job (LiveLocation.tsx,
    // TM05-103), which also clears a remembered denial.
    // Don't yank the map away from someone who has already started exploring it.
    let moved = false;
    const onMove = (event: { originalEvent?: unknown }) => {
      if (event.originalEvent) moved = true;
    };
    map.on("movestart", onMove);

    let dot: maplibregl.Marker | null = null;
    void locateStart(
      typeof navigator !== "undefined" ? navigator.geolocation : undefined,
      safeStorage(),
      REGIONS,
    ).then((outcome) => {
      map.off("movestart", onMove);
      if (outcome.kind === "fallback") return; // the default region is already showing
      const element = document.createElement("div");
      element.className = "user-location-dot";
      element.setAttribute("aria-label", "Your location");
      dot = new maplibregl.Marker({ element }).setLngLat(outcome.center).addTo(map);
      if (!moved) {
        map.easeTo({
          center: outcome.center,
          zoom: LOCATED_ZOOM,
          duration: prefersReducedMotion() ? 0 : 1200,
        });
      }
      if (outcome.kind === "outside") setOutside(outcome);
    });

    return () => {
      map.off("movestart", onMove);
      dot?.remove();
    };
  }, [map]);

  if (!outside) return null;
  return (
    <div className="banner location-notice" role="status">
      <span>
        CampSite has no data where you are yet. The nearest covered region,{" "}
        <strong>{outside.nearest.label}</strong>, is {aboutKm(outside.distanceKm)} away.
      </span>{" "}
      <button
        type="button"
        className="link-button"
        onClick={() => {
          onRegion(outside.nearest);
          setOutside(null);
        }}
      >
        Go to the {outside.nearest.label}
      </button>{" "}
      <button
        type="button"
        className="link-button location-dismiss"
        aria-label="Dismiss"
        onClick={() => setOutside(null)}
      >
        ×
      </button>
    </div>
  );
}
