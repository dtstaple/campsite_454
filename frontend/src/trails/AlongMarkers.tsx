/**
 * What the campsite search and the overnight plan put on the map (TM05-99, TM05-81):
 *
 *   - a marker for every potential spot: a dashed ring in the --candidate-* colours, so it
 *     can never be mistaken for a mapped campsite (solid circles) or read as a score;
 *   - a numbered marker for every night of the plan, on top;
 *   - the open candidate's detail: a popup listing the checks it passed, what was not
 *     checked, and the "+ Night" button.
 *
 * HTML markers, like waypoints: there are at most a handful, and they need no change to
 * the shared layer code. They show whether or not the Campsites layer is on, because
 * they belong to the trail search, not to that layer.
 */

import { useEffect, useMemo } from "react";
import { createPortal } from "react-dom";
import * as maplibregl from "maplibre-gl";
import type { PlanStop } from "../plans/api";
import { numericToken } from "../theme";
import type { Candidate } from "./candidates";
import { prefersReducedMotion } from "./terrain3d";

interface Props {
  map: maplibregl.Map | null;
  candidates: readonly Candidate[];
  /** The plan's stops, in night order, for the numbered markers. */
  nights: readonly PlanStop[];
  open: Candidate | null;
  onOpen: (candidate: Candidate | null) => void;
  /** The "+ Night" button in the popup; omitted when signed out. */
  stop?: { chosen: boolean; night?: number; onToggle: () => void };
}

export default function AlongMarkers({ map, candidates, nights, open, onOpen, stop }: Props) {
  // --- candidate markers -------------------------------------------------------------------
  useEffect(() => {
    if (!map) return;
    const markers = candidates.map((candidate) => {
      const element = document.createElement("button");
      element.type = "button";
      element.className = "candidate-marker";
      element.setAttribute("aria-label", `${candidate.label} at mile ${(candidate.distance_along_m / 1609.344).toFixed(1)}`);
      element.title = candidate.label;
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        onOpen(candidate);
      });
      return new maplibregl.Marker({ element, anchor: "center" })
        .setLngLat([candidate.lon, candidate.lat])
        .addTo(map);
    });
    return () => markers.forEach((marker) => marker.remove());
  }, [map, candidates, onOpen]);

  // --- numbered nights -----------------------------------------------------------------------
  useEffect(() => {
    if (!map) return;
    const markers = nights.map((night) => {
      const element = document.createElement("div");
      element.className = `night-marker${night.kind === "candidate" ? " is-unverified" : ""}`;
      element.textContent = String(night.night);
      element.setAttribute("aria-label", `Night ${night.night}: ${night.display_name ?? "campsite"}`);
      element.title = `Night ${night.night}: ${night.display_name ?? "campsite"}`;
      return new maplibregl.Marker({ element, anchor: "bottom", offset: [0, -6] })
        .setLngLat([night.lon, night.lat])
        .addTo(map);
    });
    return () => markers.forEach((marker) => marker.remove());
  }, [map, nights]);

  // --- the open candidate's detail -----------------------------------------------------------
  // The popup's content node belongs to the open candidate; the effect only mounts it.
  const slot = useMemo(() => (open ? document.createElement("div") : null), [open]);
  useEffect(() => {
    if (!map || !open || !slot) return;
    const popup = new maplibregl.Popup({
      closeButton: true,
      maxWidth: "300px",
      offset: 14,
      className: "candidate-popup",
    })
      .setLngLat([open.lon, open.lat])
      .setDOMContent(slot)
      .addTo(map);
    // The detail opens above the point; bring the point down if it would be cut off.
    const room = numericToken("--candidate-popup-room", 380);
    const { y } = map.project([open.lon, open.lat]);
    if (y < room) map.panBy([0, y - room], { duration: prefersReducedMotion() ? 0 : 300 });
    const onClose = () => onOpen(null);
    popup.on("close", onClose);
    return () => {
      popup.off("close", onClose);
      popup.remove();
    };
  }, [map, open, slot, onOpen]);

  if (!slot || !open) return null;
  return createPortal(<CandidateDetail candidate={open} stop={stop} />, slot);
}

export function CandidateDetail({
  candidate,
  stop,
}: {
  candidate: Candidate;
  stop?: Props["stop"];
}) {
  return (
    <div className="candidate-detail">
      <div className="candidate-detail-label">{candidate.label}</div>
      <div className="candidate-detail-meta">
        <span className="candidate-confidence" title={candidate.confidence.reason}>
          {candidate.confidence.label}
        </span>
        <span>mi {(candidate.distance_along_m / 1609.344).toFixed(1)}</span>
        <span>{Math.round(candidate.distance_from_route_m)} m off trail</span>
        {candidate.score !== null && <span>computed score {candidate.score}</span>}
      </div>
      <div className="candidate-detail-title">Checks it passed</div>
      <ul className="candidate-checks">
        {candidate.checks.map((check) => (
          <li key={check.key}>
            <span className="candidate-check" aria-hidden="true">
              ✓
            </span>
            {check.label}
          </li>
        ))}
      </ul>
      <p className="candidate-not-checked">{candidate.not_checked}</p>
      {candidate.rule && (
        <p className="candidate-rule">
          “{candidate.rule.text}”{" "}
          <a href={candidate.rule.source} target="_blank" rel="noopener noreferrer">
            NYS DEC
          </a>
        </p>
      )}
      {stop && (
        <button
          type="button"
          className="trail-stop"
          aria-pressed={stop.chosen}
          onClick={stop.onToggle}
        >
          {stop.chosen ? (stop.night ? `Night ${stop.night}` : "Night") : "+ Night"}
        </button>
      )}
    </div>
  );
}
