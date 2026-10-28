/**
 * Peak and trailhead symbol layers (TM05-122).
 *
 * Both are GeoJSON sources fed by Discover's refresh() with `layers=peaks,trailheads`,
 * labelled in landmarks.ts before setData(). The icons are drawn here on a canvas, in the
 * theme.css colours, so there is no sprite to host and no hex value outside the theme.
 *
 * A peak is a summit triangle with "Name · 4,322 ft" under it; a trailhead is a round
 * marker with a signpost and its name. Labels give way before icons (`text-optional`),
 * and higher peaks win a collision over lower ones. Over satellite imagery the labels
 * switch to the --map-landmark-*-imagery tokens, like the contours do.
 */

import type * as maplibregl from "maplibre-gl";
import { landmarkColors, numericToken } from "../theme";
import { LABEL_PROPERTY, PEAK_MIN_ZOOM, TRAILHEAD_MIN_ZOOM } from "./landmarks";

export const PEAKS_LAYER = "peaks-symbol";
export const TRAILHEADS_LAYER = "trailheads-symbol";

const PEAK_ICON = "landmark-peak";
const TRAILHEAD_ICON = "landmark-trailhead";

/** Icons are drawn at twice their CSS size so they stay sharp on high-DPI screens. */
const PIXEL_RATIO = 2;

type Basemap = "standard" | "satellite";

/** One icon as raw pixels, for map.addImage(). */
function drawIcon(draw: (context: CanvasRenderingContext2D, size: number) => void) {
  const size = numericToken("--map-landmark-icon-size", 14) * PIXEL_RATIO;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  if (!context) return null;
  draw(context, size);
  return context.getImageData(0, 0, size, size);
}

function peakIcon(fill: string, ring: string) {
  return drawIcon((context, size) => {
    const inset = size * 0.12;
    context.beginPath();
    context.moveTo(size / 2, inset);
    context.lineTo(size - inset, size - inset);
    context.lineTo(inset, size - inset);
    context.closePath();
    context.fillStyle = fill;
    context.fill();
    context.lineJoin = "round";
    context.lineWidth = size * 0.1;
    context.strokeStyle = ring;
    context.stroke();
  });
}

function trailheadIcon(fill: string, ring: string) {
  return drawIcon((context, size) => {
    const centre = size / 2;
    context.beginPath();
    context.arc(centre, centre, size * 0.42, 0, Math.PI * 2);
    context.fillStyle = fill;
    context.fill();
    context.lineWidth = size * 0.1;
    context.strokeStyle = ring;
    context.stroke();
    // A signpost: a post and a board, in the ring colour.
    context.fillStyle = ring;
    context.fillRect(centre - size * 0.04, size * 0.3, size * 0.08, size * 0.42);
    context.fillRect(centre - size * 0.2, size * 0.3, size * 0.4, size * 0.14);
  });
}

function addIcon(map: maplibregl.Map, id: string, image: ImageData | null): void {
  if (image && !map.hasImage(id)) map.addImage(id, image, { pixelRatio: PIXEL_RATIO });
}

/** Add the icons and both symbol layers. Called from addMapLayers(), after the sources. */
export function addLandmarkLayers(map: maplibregl.Map, font: string[]): void {
  const colour = landmarkColors("standard");
  addIcon(map, PEAK_ICON, peakIcon(colour.peak, colour.ring));
  addIcon(map, TRAILHEAD_ICON, trailheadIcon(colour.trailhead, colour.ring));

  const textPaint = {
    "text-color": colour.label,
    "text-halo-color": colour.halo,
    "text-halo-width": colour.haloWidth,
  };
  const textLayout = {
    "text-field": ["get", LABEL_PROPERTY] as maplibregl.ExpressionSpecification,
    "text-font": font,
    "text-size": numericToken("--map-landmark-label-size", 12),
    "text-anchor": "top" as const,
    "text-offset": [0, 0.7] as [number, number],
    "text-max-width": 10,
    // The icon stays when its label collides; only the label is dropped.
    "text-optional": true,
  };

  map.addLayer({
    id: TRAILHEADS_LAYER,
    type: "symbol",
    source: "trailheads",
    minzoom: TRAILHEAD_MIN_ZOOM,
    layout: { ...textLayout, "icon-image": TRAILHEAD_ICON, "icon-allow-overlap": true },
    paint: textPaint,
  });
  map.addLayer({
    id: PEAKS_LAYER,
    type: "symbol",
    source: "peaks",
    minzoom: PEAK_MIN_ZOOM,
    layout: {
      ...textLayout,
      "icon-image": PEAK_ICON,
      // Lower keys are placed first: the highest summit keeps its label.
      "symbol-sort-key": ["-", 0, ["coalesce", ["get", "elevation_m"], 0]],
    },
    paint: textPaint,
  });
}

/** Retint the labels for the basemap underneath (TM05-65's Map / Satellite). */
export function setLandmarkBasemap(map: maplibregl.Map, basemap: Basemap): void {
  const colour = landmarkColors(basemap);
  for (const id of [PEAKS_LAYER, TRAILHEADS_LAYER]) {
    if (!map.getLayer(id)) continue;
    map.setPaintProperty(id, "text-color", colour.label);
    map.setPaintProperty(id, "text-halo-color", colour.halo);
    map.setPaintProperty(id, "text-halo-width", colour.haloWidth);
  }
}
