/**
 * The selected campsite (TM05-69): what is selected, and where the camera goes for it.
 *
 * Pure -- no DOM, no MapLibre instance -- so node --test can load it. SelectedCampsite.tsx
 * does the drawing; this file decides.
 */

import { gradeFor, gradeToken, isScore } from "../score/grade.ts";

/**
 * One selected campsite. Where it was picked from supplies what it already knows: a map
 * click knows the feature's position and properties, a trail-list row knows the site's
 * position, name and score. The detail endpoint fills in the rest when it arrives.
 */
export interface CampsiteSelection {
  id: string;
  lon: number;
  lat: number;
  name: string | null;
  /** Contract-1 score (0-100), or null when the source of the selection had none. */
  score: number | null;
}

/** The selection for a map feature, or null if it has no usable id or point. */
export function selectionFromFeature(feature: {
  properties: Record<string, unknown> | null;
  geometry: { type: string; coordinates?: unknown };
}, id: string): CampsiteSelection | null {
  if (!id || feature.geometry.type !== "Point") return null;
  const [lon, lat] = feature.geometry.coordinates as [number, number];
  const props = feature.properties ?? {};
  return {
    id,
    lon,
    lat,
    name: typeof props.name === "string" && props.name ? props.name : null,
    score: isScore(props.score) ? props.score : null,
  };
}

/** The pin's label: the best name we have, and the score when there is one. */
export function pinLabel(name: string | null, score: number | null): { name: string; score: string | null } {
  return { name: name || "Campsite", score: isScore(score) ? String(Math.round(score)) : null };
}

/** The CSS custom property for the pin head: the score grade, or the no-score neutral. */
export function pinColorToken(score: number | null): string {
  return gradeToken(gradeFor(score));
}

// --- camera ----------------------------------------------------------------------------

/** In 3D the camera tilts to this, so the pin and the ground around it read as relief. */
export const SELECTED_PITCH = 60;
/** ...and comes in at least this close, unless the user is already closer. */
export const SELECTED_ZOOM = 15.5;

export interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface Padding {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/**
 * Camera padding that keeps the site clear of the side panel. On a wide screen the panel
 * is a column on the right, so the right padding is its width plus the gap to the edge;
 * on a phone it is a sheet along the bottom (trails.css, max-width 720px), so the bottom
 * padding is its height instead. `margin` is the breathing room on every side.
 * selectionCamera turns this into an offset.
 */
export function panelPadding(map: Rect, panel: Rect | null, margin: number): Padding {
  const padding = { top: margin, right: margin, bottom: margin, left: margin };
  if (!panel) return padding;
  const mapWidth = map.right - map.left;
  const isColumn = panel.right - panel.left < mapWidth * 0.75;
  if (isColumn) padding.right = Math.max(margin, map.right - panel.left + margin);
  else padding.bottom = Math.max(margin, map.bottom - panel.top + margin);
  return padding;
}

export interface CameraView {
  zoom: number;
  bearing: number;
  /** True when 3D terrain is on. */
  terrain: boolean;
}

/**
 * Where to put the camera for a selected site. 3D keeps the bearing the user chose, tilts
 * to SELECTED_PITCH and closes in to SELECTED_ZOOM; 2D only re-centres.
 *
 * The panel room is an `offset`, not `padding`: MapLibre keeps a camera move's padding as
 * the map's padding afterwards, so every later move (a region button, fitBounds) would
 * stay shifted left after the panel closed. An offset moves the site to the middle of the
 * visible part of the map for this move only.
 */
export function selectionCamera(view: CameraView, center: [number, number], padding: Padding) {
  const offset: [number, number] = [
    (padding.left - padding.right) / 2,
    (padding.top - padding.bottom) / 2,
  ];
  if (!view.terrain) return { center, offset };
  return {
    center,
    offset,
    bearing: view.bearing,
    pitch: SELECTED_PITCH,
    zoom: Math.max(view.zoom, SELECTED_ZOOM),
  };
}
