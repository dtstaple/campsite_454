/**
 * Turning 3D terrain on and off (TM05-62).
 *
 * Uses the raster-dem source the hillshade already reads (map/layers.ts,
 * TERRAIN_SOURCE_ID): AWS Terrain Tiles with encoding "terrarium", verified when the
 * hillshade was added. One source for both means one set of DEM tiles in memory, and the
 * shading and the relief can never disagree.
 */

import type * as maplibregl from "maplibre-gl";
import { TERRAIN_SOURCE_ID } from "../map/layers";
import { numericToken } from "../theme";

export const MAX_PITCH_3D = 85;

/** Enable terrain; returns the previous pitch limit so disable3D can restore it. */
export function enable3D(map: maplibregl.Map): number {
  const previousMaxPitch = map.getMaxPitch();
  if (!map.getSource(TERRAIN_SOURCE_ID)) return previousMaxPitch;
  map.setMaxPitch(MAX_PITCH_3D);
  map.setTerrain({
    source: TERRAIN_SOURCE_ID,
    exaggeration: numericToken("--map-terrain-exaggeration", 1.4),
  });
  return previousMaxPitch;
}

export function disable3D(map: maplibregl.Map, previousMaxPitch: number): void {
  map.setTerrain(null);
  map.easeTo({ pitch: 0, bearing: 0, duration: 600 });
  // Pitch has to come down before the limit can, or setMaxPitch clamps mid-animation.
  map.once("moveend", () => map.setMaxPitch(previousMaxPitch));
}

export function prefersReducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}
