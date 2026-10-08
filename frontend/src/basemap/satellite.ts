/**
 * Esri World Imagery as an alternative basemap (TM05-65).
 *
 * Verified with curl over the Adirondacks on 2026-10-02 (docs/basemaps.md):
 *   - URL order is {z}/{y}/{x} -- row before column, unlike most XYZ services.
 *   - Real JPEG tiles through zoom 19 at every one of 23 sampled points. From zoom 20 Esri
 *     answers 200 with a 2,521-byte grey "Map data not yet available" JPEG, so the source
 *     stops at 19 and MapLibre overzooms instead of drawing grey squares.
 *   - Attribution is the service's own copyrightText.
 *
 * The imagery is a raster layer slotted beneath the basemap's first label layer: it covers
 * the vector basemap's fills and roads, keeps its place names on top, and stays below every
 * CampSite data layer (those are added after the style loads, so they are already above).
 */

import type * as maplibregl from "maplibre-gl";
import { CONTOUR_LINE_LAYER } from "../map/contours";
import { SLOPE_LAYER } from "../slope/slopeLayer";
import { numericToken, token } from "../theme";

export const IMAGERY_SOURCE = "esri-world-imagery";
export const IMAGERY_LAYER = "esri-world-imagery";
export const TRAILS_CASING = "trails-casing-imagery";
export const WATER_CASING = "water-line-casing-imagery";

export const IMAGERY_TILES =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
export const IMAGERY_MAX_ZOOM = 19;
export const IMAGERY_ATTRIBUTION =
  '<a href="https://goto.arcgisonline.com/maps/World_Imagery" target="_blank" rel="noopener">' +
  "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community</a>";

function firstSymbolLayerId(map: maplibregl.Map): string | undefined {
  return map.getStyle().layers?.find((layer) => layer.type === "symbol")?.id;
}

/** Add the imagery source, its layer and the over-imagery casings, all hidden. Idempotent. */
export function addImageryLayers(map: maplibregl.Map): void {
  if (map.getSource(IMAGERY_SOURCE)) return;
  map.addSource(IMAGERY_SOURCE, {
    type: "raster",
    tiles: [IMAGERY_TILES],
    // Esri tiles are 256 px. Declaring 256 (not 512) makes MapLibre fetch the zoom level
    // that matches the screen, which is what keeps imagery sharp when pitched in 3D.
    tileSize: 256,
    maxzoom: IMAGERY_MAX_ZOOM,
    attribution: IMAGERY_ATTRIBUTION,
  });
  map.addLayer(
    {
      id: IMAGERY_LAYER,
      type: "raster",
      source: IMAGERY_SOURCE,
      layout: { visibility: "none" },
      paint: {
        // Imagery is bright and busy; capping its brightness a little lets the trail and
        // water linework sit on top of it rather than in it.
        "raster-brightness-max": numericToken("--map-imagery-brightness-max", 0.85),
        "raster-saturation": numericToken("--map-imagery-saturation", -0.1),
      },
    },
    // Under the slope shading (TM05-84) and contour lines (TM05-83) when they exist, so
    // both draw over the imagery.
    [SLOPE_LAYER, CONTOUR_LINE_LAYER].find((id) => map.getLayer(id)) ??
      firstSymbolLayerId(map),
  );

  // Dark casings under the trail and stream lines, shown only over imagery: an orange
  // hairline on green-brown forest needs an edge to read; on the dark basemap it does not.
  const casing = token("--map-casing-imagery") || "#15130f";
  const opacity = numericToken("--map-casing-imagery-opacity", 0.75);
  const extra = numericToken("--map-casing-imagery-extra-width", 2.4);
  if (map.getLayer("trails-line")) {
    map.addLayer(
      {
        id: TRAILS_CASING,
        type: "line",
        source: "trails",
        layout: { visibility: "none", "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": casing,
          "line-opacity": opacity,
          "line-width": numericToken("--map-trails-width", 1.6) + extra,
        },
      },
      "trails-line",
    );
  }
  if (map.getLayer("water-line")) {
    map.addLayer(
      {
        id: WATER_CASING,
        type: "line",
        source: "water",
        filter: ["==", ["geometry-type"], "LineString"],
        layout: { visibility: "none" },
        paint: {
          "line-color": casing,
          "line-opacity": opacity,
          "line-width": numericToken("--map-water-line-width", 1.2) + extra,
        },
      },
      "water-line",
    );
  }
}

export function setImageryVisible(map: maplibregl.Map, visible: boolean): void {
  const value = visible ? "visible" : "none";
  for (const id of [IMAGERY_LAYER, TRAILS_CASING, WATER_CASING]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", value);
  }
}
