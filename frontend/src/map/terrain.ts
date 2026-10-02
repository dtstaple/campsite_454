/**
 * Terrain hillshade: the visual hero of the map, drawn from a keyless DEM.
 *
 * Kept out of layers.ts on purpose. layers.ts defines the data layers the API feeds; this
 * is a raster the map fetches by itself, and it slots *under* everything we draw and
 * under the basemap's labels, so it does not disturb the order layers.ts relies on.
 *
 * Source: AWS Terrain Tiles (the Tilezen/Joerd tileset on the AWS Open Data registry),
 * Terrarium encoding. Verified before use -- see the run summary in
 * artifacts/ui-direction-audit.md. The encoding has to be stated: MapLibre defaults
 * raster-dem to "mapbox", and decoding Terrarium tiles as Mapbox RGB renders noise
 * without any error.
 *
 * Shading only. No 3D terrain and no elevation sampling -- that is 3DEP work for a later
 * sprint, and a visual tile is not a data source.
 */

import type * as maplibregl from "maplibre-gl";
import { mapHillshade } from "../theme";

export const TERRAIN_SOURCE_ID = "terrain-dem";
export const HILLSHADE_LAYER_ID = "terrain-hillshade";

const TERRAIN_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";

const TERRAIN_ATTRIBUTION =
  '<a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md" ' +
  'target="_blank" rel="noopener">Terrain: Mapzen, USGS 3DEP and others</a>';

/**
 * The basemap's first label layer, so the shading goes beneath every place name and
 * road label rather than over them. Undefined when the style has no labels, which
 * appends the layer -- still below ours, because this runs before addMapLayers().
 */
function firstSymbolLayerId(map: maplibregl.Map): string | undefined {
  return map.getStyle().layers?.find((layer) => layer.type === "symbol")?.id;
}

/** Add the DEM source and the hillshade layer. Call once on `load`, before addMapLayers. */
export function addHillshade(map: maplibregl.Map, visible: boolean): void {
  const paint = mapHillshade();

  map.addSource(TERRAIN_SOURCE_ID, {
    type: "raster-dem",
    tiles: [TERRAIN_TILES],
    encoding: "terrarium",
    tileSize: 256,
    // The tileset's native maximum; MapLibre overzooms past it.
    maxzoom: 15,
    attribution: TERRAIN_ATTRIBUTION,
  });

  map.addLayer(
    {
      id: HILLSHADE_LAYER_ID,
      type: "hillshade",
      source: TERRAIN_SOURCE_ID,
      layout: { visibility: visible ? "visible" : "none" },
      paint: {
        "hillshade-shadow-color": paint.shadow,
        "hillshade-highlight-color": paint.highlight,
        "hillshade-accent-color": paint.accent,
        "hillshade-exaggeration": paint.exaggeration,
        // Light from the northwest, the cartographic convention: ridges read as raised
        // rather than as valleys.
        "hillshade-illumination-direction": 315,
      },
    },
    firstSymbolLayerId(map),
  );
}

/** Show or hide the shading without refetching anything. */
export function setHillshadeVisible(map: maplibregl.Map, visible: boolean): void {
  if (!map.getLayer(HILLSHADE_LAYER_ID)) return;
  map.setLayoutProperty(HILLSHADE_LAYER_ID, "visibility", visible ? "visible" : "none");
}
