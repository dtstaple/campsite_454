/**
 * Contour lines (TM05-83), generated in the browser from the same Terrarium DEM tiles the
 * hillshade and 3D terrain use (layers.ts TERRAIN_TILES): no new tile source.
 *
 * maplibre-contour (BSD-3-Clause, no dependencies) registers a MapLibre protocol that
 * turns DEM tiles into contour vector tiles in a web worker, so the main thread never
 * runs marching squares. It fetches the same URLs the hillshade does, so the browser's
 * HTTP cache serves both. Intervals are in contourConfig.ts; colours in theme.css.
 *
 * Layer order: under the basemap's labels and every data layer, over the hillshade, and
 * over satellite imagery (satellite.ts inserts the imagery beneath CONTOUR_LINE_LAYER).
 * Over imagery the lines switch to the --map-contour-imagery-* colours, because brown
 * lines tuned for the dark basemap vanish on forest.
 */

import mlcontour from "maplibre-contour";
import * as maplibregl from "maplibre-gl";
import { numericToken, token } from "../theme";
import { TERRAIN_TILES } from "./layers";
import {
  CONTOUR_MIN_ZOOM,
  CONTOUR_THRESHOLDS_FT,
  FT_PER_M,
  INDEX_LEVEL,
} from "./contourConfig";

export const CONTOUR_SOURCE = "contours";
export const CONTOUR_LINE_LAYER = "contour-lines";
export const CONTOUR_LABEL_LAYER = "contour-labels";

/** Terrarium's useful detail in the US runs out around here; deeper zooms overzoom it. */
const DEM_MAX_ZOOM = 14;

let demSource: InstanceType<typeof mlcontour.DemSource> | null = null;

/** One DEM source and protocol for the page, however many times the map is rebuilt. */
function dem() {
  if (!demSource) {
    demSource = new mlcontour.DemSource({
      url: TERRAIN_TILES,
      encoding: "terrarium",
      maxzoom: DEM_MAX_ZOOM,
      worker: true,
    });
    demSource.setupMaplibre(maplibregl);
  }
  return demSource;
}

/** A font the style's glyph server has: the first one its own labels use. */
function labelFont(map: maplibregl.Map): string[] {
  for (const layer of map.getStyle().layers ?? []) {
    if (layer.type !== "symbol") continue;
    const font = layer.layout?.["text-font"];
    if (Array.isArray(font) && font.every((f) => typeof f === "string")) return font as string[];
  }
  return ["Stadia Regular"];
}

function firstSymbolLayerId(map: maplibregl.Map): string | undefined {
  return map.getStyle().layers?.find((layer) => layer.type === "symbol")?.id;
}

type Basemap = "standard" | "satellite";

function colors(basemap: Basemap) {
  const suffix = basemap === "satellite" ? "-imagery" : "";
  return {
    line: token(`--map-contour${suffix}`),
    index: token(`--map-contour-index${suffix}`),
    label: token(`--map-contour-label${suffix}`),
    halo: token(`--map-contour-label-halo${suffix}`),
  };
}

const isIndexLine: maplibregl.ExpressionSpecification = ["==", ["get", "level"], INDEX_LEVEL];

/** Add the contour source and layers. Call once on `load`, after the hillshade. */
export function addContourLayers(map: maplibregl.Map, visible: boolean, basemap: Basemap): void {
  if (map.getSource(CONTOUR_SOURCE)) return;
  const thresholds: Record<number, number[]> = {};
  for (const [zoom, pair] of Object.entries(CONTOUR_THRESHOLDS_FT)) thresholds[Number(zoom)] = [...pair];

  map.addSource(CONTOUR_SOURCE, {
    type: "vector",
    tiles: [
      dem().contourProtocolUrl({
        multiplier: FT_PER_M, // elevations and thresholds in feet
        thresholds,
        elevationKey: "ele",
        levelKey: "level",
        contourLayer: "contours",
      }),
    ],
    minzoom: CONTOUR_MIN_ZOOM,
    maxzoom: 15,
  });

  const c = colors(basemap);
  const visibility = visible ? "visible" : "none";
  const before = firstSymbolLayerId(map);
  map.addLayer(
    {
      id: CONTOUR_LINE_LAYER,
      type: "line",
      source: CONTOUR_SOURCE,
      "source-layer": "contours",
      minzoom: CONTOUR_MIN_ZOOM,
      layout: { visibility, "line-join": "round" },
      paint: {
        "line-color": ["case", isIndexLine, c.index, c.line],
        "line-width": [
          "case",
          isIndexLine,
          numericToken("--map-contour-index-width", 1.4),
          numericToken("--map-contour-width", 0.6),
        ],
      },
    },
    before,
  );
  map.addLayer(
    {
      id: CONTOUR_LABEL_LAYER,
      type: "symbol",
      source: CONTOUR_SOURCE,
      "source-layer": "contours",
      minzoom: CONTOUR_MIN_ZOOM,
      // Index lines only, as on a printed topo: labelling every line is clutter.
      filter: isIndexLine,
      layout: {
        visibility,
        "symbol-placement": "line",
        "text-field": ["concat", ["number-format", ["get", "ele"], { locale: "en-US" }], " ft"],
        "text-font": labelFont(map),
        "text-size": numericToken("--map-contour-label-size", 10),
        "text-max-angle": 25,
        "symbol-spacing": 280,
        "text-padding": 4,
      },
      paint: {
        "text-color": c.label,
        "text-halo-color": c.halo,
        "text-halo-width": 1.4,
      },
    },
    before,
  );
}

export function setContoursVisible(map: maplibregl.Map, visible: boolean): void {
  for (const id of [CONTOUR_LINE_LAYER, CONTOUR_LABEL_LAYER]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
}

/** Retint the contours for the basemap underneath (TM05-65's Map / Satellite). */
export function setContourBasemap(map: maplibregl.Map, basemap: Basemap): void {
  if (!map.getLayer(CONTOUR_LINE_LAYER)) return;
  const c = colors(basemap);
  map.setPaintProperty(CONTOUR_LINE_LAYER, "line-color", ["case", isIndexLine, c.index, c.line]);
  map.setPaintProperty(CONTOUR_LABEL_LAYER, "text-color", c.label);
  map.setPaintProperty(CONTOUR_LABEL_LAYER, "text-halo-color", c.halo);
}
