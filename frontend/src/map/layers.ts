/**
 * The MapLibre source and layer definitions, as data.
 *
 * The only place layers are defined. Nothing here is stateful: Discover.tsx calls
 * addMapSources() and addMapLayers() once on the map's `load` event and feeds the
 * sources afterwards from its refresh(). Kept out of the component so it reads as
 * composition rather than as a hundred lines of paint properties.
 *
 * Every colour, width and opacity comes from theme.css via theme.ts. MapLibre paint
 * properties cannot take a `var(--x)`, so they are read back out of the stylesheet
 * instead of being written twice.
 */

import type * as maplibregl from "maplibre-gl";
import type { FeatureCollection as GeoJsonFeatureCollection } from "geojson";
import { mapColors, mapHillshade, mapPaint, scoreColors } from "../theme";
import { scoreColorExpression } from "../score/grade";
import { campsiteHighlightPaint } from "../campsite/highlight";
import { SOURCE_ID_PROPERTY } from "./featureIds";
import type { LayerName } from "../api";
import type { ActivityMode } from "../modes/modes";

export const LAYERS: readonly { name: LayerName; label: string }[] = [
  { name: "public-land", label: "Public land" },
  { name: "water", label: "Water" },
  { name: "trails", label: "Trails" },
  { name: "campsites", label: "Campsites" },
];

export type LayerEntry = (typeof LAYERS)[number];

/**
 * LAYERS in an activity mode's emphasis order, for the layer panel. Layers the mode
 * does not mention go last. Ordering only -- draw order is fixed by addMapLayers().
 */
export function orderedLayers(mode: ActivityMode): LayerEntry[] {
  const rank = (name: LayerName) => {
    const index = mode.emphasis.indexOf(name);
    return index === -1 ? mode.emphasis.length : index;
  };
  return [...LAYERS].sort((a, b) => rank(a.name) - rank(b.name));
}

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
export type ClickableLayer = Exclude<LayerName, "public-land">;

export const CLICKABLE: readonly { id: string; layer: ClickableLayer }[] = [
  { id: "campsites-point", layer: "campsites" },
  { id: "trails-hit", layer: "trails" },
  { id: "water-line-hit", layer: "water" },
  { id: "water-fill", layer: "water" },
];

export const CLICKABLE_IDS: string[] = CLICKABLE.map((entry) => entry.id);

/** One GeoJSON source per layer. The API output goes in unmodified. */
export function addMapSources(map: maplibregl.Map): void {
  for (const layer of LAYERS) {
    map.addSource(layer.name, {
      type: "geojson",
      data: EMPTY,
      // TM05-69: campsites are keyed by source_id so feature-state can mark the selected one.
      ...(layer.name === "campsites" ? { promoteId: SOURCE_ID_PROPERTY } : {}),
    });
  }
}

/**
 * Every draw layer, bottom to top: public land, water, trails, then campsite markers.
 * Each `-hit` layer sits directly above the line it widens.
 */
export function addMapLayers(map: maplibregl.Map): void {
  const colour = mapColors();
  const paint = mapPaint();

  // Public land first, so every other layer draws on top of it. It is background:
  // a quiet tint saying which ground is legally campable, under the water, trails
  // and campsites the user actually came to read.
  map.addLayer({
    id: "public-land-fill",
    type: "fill",
    source: "public-land",
    paint: {
      "fill-color": colour.publicLand,
      "fill-opacity": paint.publicLandFillOpacity,
    },
  });
  map.addLayer({
    id: "public-land-outline",
    type: "line",
    source: "public-land",
    paint: {
      "line-color": colour.publicLand,
      "line-width": paint.publicLandLineWidth,
      "line-opacity": paint.publicLandLineOpacity,
    },
  });

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

  // TM05-69 wraps these values: unchanged until a campsite is selected or hovered.
  const highlight = campsiteHighlightPaint({
    radius: paint.campsitesRadius,
    opacity: paint.campsitesOpacity,
    strokeWidth: paint.campsitesStrokeWidth,
    strokeColor: colour.campsiteStroke,
  });
  map.addLayer({
    id: "campsites-point",
    type: "circle",
    source: "campsites",
    paint: {
      "circle-radius": highlight.radius,
      "circle-color": scoreColorExpression(scoreColors()) as maplibregl.ExpressionSpecification,
      "circle-opacity": highlight.opacity,
      "circle-stroke-width": highlight.strokeWidth,
      "circle-stroke-color": highlight.strokeColor,
    },
  });
}

// --- terrain -----------------------------------------------------------------------
//
// Hillshade from a keyless DEM: AWS Terrain Tiles (the Tilezen/Joerd tileset on the AWS
// Open Data registry). Unlike the layers above it is a raster the map fetches itself,
// so refresh() never feeds it; it is shown and hidden in place instead. It goes under
// the basemap's labels and under every data layer.
//
// The encoding has to be stated: MapLibre defaults raster-dem to "mapbox", and decoding
// Terrarium tiles as Mapbox RGB renders noise without any error. The URL, encoding and
// curl verification are recorded in artifacts/ui-direction-audit.md.
//
// Shading only. No 3D terrain and no elevation sampling -- a visual tile is not a data
// source; elevation data is 3DEP work for a later sprint.

export const TERRAIN_SOURCE_ID = "terrain-dem";
export const HILLSHADE_LAYER_ID = "terrain-hillshade";

export const TERRAIN_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";

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
export function addTerrainLayers(map: maplibregl.Map, visible: boolean): void {
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
