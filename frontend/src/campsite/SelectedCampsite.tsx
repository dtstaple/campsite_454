/**
 * The selected campsite on the map (TM05-69): a raised pin, a highlighted circle, and a
 * camera move that brings it into view beside the panel.
 *
 * Renders nothing into the React tree; everything it draws belongs to the map:
 *
 *   - Pin. An HTML maplibregl.Marker anchored at its bottom, so the stem's foot is the
 *     site's coordinate and, in 3D, stands on the terrain. Its head carries the score
 *     grade colour (TM05-48's --score-* tokens). MapLibre fades it (`opacityWhenCovered`)
 *     when a ridge hides the foot, rather than drawing it through the hill.
 *   - Circle. feature-state `selected` on the campsite source and a global "something is
 *     selected" flag, read by the paint in highlight.ts.
 *   - Camera. Once per selection: easeTo, offset to leave room for the panel (no animation
 *     with reduced motion). 3D keeps the bearing and tilts; 2D only re-centres. See
 *     selection.ts.
 */

import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import { numericToken } from "../theme";
import { prefersReducedMotion } from "../trails/terrain3d";
import { SELECTED_STATE } from "./highlight";
import {
  panelPadding,
  pinColorToken,
  pinLabel,
  selectionCamera,
  type CampsiteSelection,
} from "./selection";

const CAMPSITE_SOURCE = "campsites";
const CAMERA_MS = 900;

interface Props {
  map: maplibregl.Map | null;
  selection: CampsiteSelection | null;
  /** The detail endpoint's display name, once loaded: better than the raw name. */
  displayName: string | null;
}

function hasCampsiteSource(map: maplibregl.Map): boolean {
  return Boolean(map.getSource(CAMPSITE_SOURCE));
}

function buildPin(): { element: HTMLDivElement; name: HTMLSpanElement; score: HTMLSpanElement } {
  const element = document.createElement("div");
  element.className = "campsite-pin";
  element.setAttribute("aria-hidden", "true");
  const label = document.createElement("div");
  label.className = "campsite-pin-label";
  const name = document.createElement("span");
  name.className = "campsite-pin-name";
  const score = document.createElement("span");
  score.className = "campsite-pin-score";
  label.append(name, score);
  for (const part of ["campsite-pin-ring", "campsite-pin-stem", "campsite-pin-head"]) {
    const child = document.createElement("div");
    child.className = part;
    element.append(child);
  }
  element.append(label);
  return { element, name, score };
}

export default function SelectedCampsite({ map, selection, displayName }: Props) {
  const id = selection?.id ?? null;
  const lon = selection?.lon ?? null;
  const lat = selection?.lat ?? null;

  // --- circle highlight ------------------------------------------------------------------
  useEffect(() => {
    if (!map || !id || !hasCampsiteSource(map)) return;
    const target = { source: CAMPSITE_SOURCE, id };
    map.setFeatureState(target, { selected: true });
    map.setGlobalStateProperty(SELECTED_STATE, true);
    return () => {
      if (!hasCampsiteSource(map)) return;
      map.setFeatureState(target, { selected: false });
      map.setGlobalStateProperty(SELECTED_STATE, false);
    };
  }, [map, id]);

  // --- pin ---------------------------------------------------------------------------------
  const pin = useRef<ReturnType<typeof buildPin> | null>(null);
  useEffect(() => {
    if (!map || !id || lon === null || lat === null) return;
    const built = buildPin();
    pin.current = built;
    const marker = new maplibregl.Marker({
      element: built.element,
      anchor: "bottom",
      opacityWhenCovered: String(numericToken("--pin-covered-opacity", 0.2)),
    })
      .setLngLat([lon, lat])
      .addTo(map);
    return () => {
      marker.remove();
      pin.current = null;
    };
  }, [map, id, lon, lat]);

  const score = selection?.score ?? null;
  const name = displayName ?? selection?.name ?? null;
  useEffect(() => {
    const current = pin.current;
    if (!current) return;
    const label = pinLabel(name, score);
    current.name.textContent = label.name;
    current.score.textContent = label.score ?? "";
    current.score.hidden = label.score === null;
    current.element.style.setProperty("--pin-color", `var(${pinColorToken(score)})`);
  }, [id, lon, lat, name, score]);

  // --- camera ------------------------------------------------------------------------------
  // Once per selection: a later label or score update must not move the camera again.
  const movedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!id) movedFor.current = null;
    if (!map || !id || lon === null || lat === null || movedFor.current === id) return;
    movedFor.current = id;
    const container = map.getContainer();
    const panel = container.parentElement?.querySelector(".campsite-panel") ?? null;
    const padding = panelPadding(
      container.getBoundingClientRect(),
      panel ? panel.getBoundingClientRect() : null,
      numericToken("--space-3xl", 48),
    );
    const camera = selectionCamera(
      { zoom: map.getZoom(), bearing: map.getBearing(), terrain: Boolean(map.getTerrain()) },
      [lon, lat],
      padding,
    );
    // Reduced motion: the same move with no animation. easeTo rather than jumpTo because
    // only easeTo takes an offset, and padding would outlive the move (selection.ts).
    map.easeTo({ ...camera, duration: prefersReducedMotion() ? 0 : CAMERA_MS });
  }, [map, id, lon, lat]);

  return null;
}
