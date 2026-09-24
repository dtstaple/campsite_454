/**
 * The MapLibre source and layer definitions, as data.
 *
 * Extracted from App.tsx so that component reads as composition rather than as ninety
 * lines of paint properties. Nothing here is stateful -- addMapLayers() is called once
 * on the map's `load` event and the sources are fed afterwards by App's refresh().
 *
 * Every colour, width and opacity comes from theme.css via theme.ts. MapLibre paint
 * properties cannot take a `var(--x)`, so they are read back out of the stylesheet
 * instead of being written twice.
 */

import type * as maplibregl from "maplibre-gl";
import type { FeatureCollection as GeoJsonFeatureCollection } from "geojson";
import { mapColors, mapPaint } from "../theme";
import type { LayerName } from "../api";

export const LAYERS: readonly { name: LayerName; label: string }[] = [
  { name: "water", label: "Water" },
  { name: "trails", label: "Trails" },
  { name: "campsites", label: "Campsites" },
];

export const EMPTY: GeoJsonFeatureCollection = { type: "FeatureCollection", features: [] };

/**
 * Layers a click or hover can land on, most specific first.
 *
 * Order is the tiebreak when several sit under the cursor: a campsite marker drawn over
 * a lake should win, because it is the smaller and more deliberate target.
 *
 * Note the two `-hit` entries. A trail is drawn 1.6px wide and a stream 1.2px, which is
 * far below what anyone can reliably click, so each linework layer gets an invisible
 * companion an order of magnitude wider that exists purely to be hit. Fully transparent
 * layers still answer queryRenderedFeatures, so the visible lines stay hairline-thin
 * while the target stays comfortable.
 */
export const CLICKABLE: readonly { id: string; layer: LayerName }[] = [
  { id: "campsites-point", layer: "campsites" },
  { id: "trails-hit", layer: "trails" },
  { id: "water-line-hit", layer: "water" },
  { id: "water-fill", layer: "water" },
];

export const CLICKABLE_IDS: string[] = CLICKABLE.map((entry) => entry.id);

/** One GeoJSON source per layer. The API output goes in unmodified. */
export function addMapSources(map: maplibregl.Map): void {
  for (const layer of LAYERS) {
    map.addSource(layer.name, { type: "geojson", data: EMPTY });
  }
}

/** Every draw layer, bottom to top: water, then trails, then campsite markers. */
export function addMapLayers(map: maplibregl.Map): void {
  const colour = mapColors();
  const paint = mapPaint();

  // Water: polygons filled, lines stroked. docs/api.md says one collection carries
  // both, so each is filtered by geometry type rather than by endpoint.
  map.addLayer({
    id: "water-fill",
    type: "fill",
    source: "water",
    filter: ["==", ["geometry-type"], "Polygon"],
    paint: { "fill-color": colour.water, "fill-opacity": paint.waterFillOpacity },
  });
  map.addLayer({
    id: "water-line",
    type: "line",
    source: "water",
    filter: ["==", ["geometry-type"], "LineString"],
    paint: {
      "line-color": colour.water,
      "line-width": paint.waterLineWidth,
      "line-opacity": paint.waterLineOpacity,
    },
  });
  map.addLayer({
    id: "water-line-hit",
    type: "line",
    source: "water",
    filter: ["==", ["geometry-type"], "LineString"],
    paint: { "line-color": colour.water, "line-width": paint.hitWidth, "line-opacity": 0 },
  });

  map.addLayer({
    id: "trails-line",
    type: "line",
    source: "trails",
    paint: {
      "line-color": colour.trails,
      "line-width": paint.trailsWidth,
      "line-opacity": paint.trailsOpacity,
    },
  });
  map.addLayer({
    id: "trails-hit",
    type: "line",
    source: "trails",
    paint: { "line-color": colour.trails, "line-width": paint.hitWidth, "line-opacity": 0 },
  });

  map.addLayer({
    id: "campsites-point",
    type: "circle",
    source: "campsites",
    paint: {
      "circle-radius": paint.campsitesRadius,
      "circle-color": colour.campsites,
      "circle-opacity": paint.campsitesOpacity,
      "circle-stroke-width": paint.campsitesStrokeWidth,
      "circle-stroke-color": colour.campsiteStroke,
    },
  });
}
