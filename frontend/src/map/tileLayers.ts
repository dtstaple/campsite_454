/**
 * Which map layers come from vector tiles, and their source specs (TM05-140).
 *
 * Trails, water and public land are served as Mapbox Vector Tiles by
 * /api/tiles/<layer>/<z>/<x>/<y>.mvt (backend/api/tiles.py). Campsites stay on the
 * GeoJSON API, because their colours depend on the signed-in user's weights.
 *
 * Each tile source holds one MVT layer, named like the source, so every draw layer's
 * `source-layer` is its source's name. `minzoom` must match the backend's TileLayer.
 * Below it the server answers 204, so MapLibre requests nothing. Pure data, so
 * node --test can load it.
 */

import type { LayerName } from "../api";

export type TiledLayer = Extract<LayerName, "trails" | "water" | "public-land">;

/** Tiles exist up to this zoom; MapLibre overzooms beyond it. */
export const TILE_MAX_ZOOM = 14;

export const TILED: Readonly<Record<TiledLayer, { minzoom: number }>> = {
  // Linework under zoom 9 is sub-pixel (MIN_ZOOM_FOR_LINEWORK in api.ts).
  trails: { minzoom: 9 },
  water: { minzoom: 9 },
  "public-land": { minzoom: 0 },
};

export function isTiled(layer: LayerName): layer is TiledLayer {
  return layer in TILED;
}

export function tileUrl(apiBase: string, layer: TiledLayer): string {
  return `${apiBase}/api/tiles/${layer}/{z}/{x}/{y}.mvt`;
}

/** The MapLibre source for one tiled layer. */
export function vectorSource(apiBase: string, layer: TiledLayer) {
  return {
    type: "vector" as const,
    tiles: [tileUrl(apiBase, layer)],
    minzoom: TILED[layer].minzoom,
    maxzoom: TILE_MAX_ZOOM,
  };
}

/** Layer metadata key marking a draw layer shown only over the satellite basemap. */
export const IMAGERY_ONLY = "campsite:imagery-only";

/**
 * Visibility for one draw layer of a tiled source. A layer the user turned off is
 * hidden. A satellite-only casing (`imageryOnly`) also needs the satellite basemap on.
 */
export function drawLayerVisibility(
  layerOn: boolean,
  imageryOnly: boolean,
  imageryOn: boolean,
): "visible" | "none" {
  return layerOn && (!imageryOnly || imageryOn) ? "visible" : "none";
}
