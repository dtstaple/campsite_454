/**
 * Map sources and layers for named routes (TM05-61).
 *
 * Kept beside the trail feature rather than in map/layers.ts: these layers belong to the
 * trail panel and are added by TrailInsight once the base layers exist. They slot in
 * beneath the trail linework (`trails-line`), so routes read as a quiet backbone under
 * the segments, and the selected route is drawn above everything but campsites.
 */

import type * as maplibregl from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import { numericToken, token } from "../theme";

export const ROUTES_SOURCE = "named-routes";
export const SELECTED_SOURCE = "named-route-selected";
export const ALONG_SOURCE = "named-route-campsites";

export const ROUTES_LINE = "named-routes-line";
export const ROUTES_HIT = "named-routes-hit";
export const SELECTED_CASING = "named-route-selected-casing";
export const SELECTED_LINE = "named-route-selected-line";
export const SELECTED_HIT = "named-route-selected-hit";
export const ALONG_POINTS = "named-route-campsites-point";

export const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

function before(map: maplibregl.Map, id: string): string | undefined {
  return map.getLayer(id) ? id : undefined;
}

export function addRouteLayers(map: maplibregl.Map): void {
  if (map.getSource(ROUTES_SOURCE)) return;
  const route = token("--map-route") || "#e9d8a6";
  const selected = token("--map-route-selected") || "#ffd166";
  const casing = token("--map-route-casing") || "#15130f";
  const campsite = token("--map-campsites") || "#ff5a68";
  const stroke = token("--text-primary") || "#ede7d9";
  const hitWidth = numericToken("--map-hit-width", 14);

  map.addSource(ROUTES_SOURCE, { type: "geojson", data: EMPTY });
  map.addSource(SELECTED_SOURCE, { type: "geojson", data: EMPTY });
  map.addSource(ALONG_SOURCE, { type: "geojson", data: EMPTY });

  const underTrails = before(map, "trails-line");
  map.addLayer(
    {
      id: ROUTES_LINE,
      type: "line",
      source: ROUTES_SOURCE,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": route,
        "line-opacity": numericToken("--map-route-opacity", 0.35),
        "line-width": numericToken("--map-route-width", 2.5),
      },
    },
    underTrails,
  );
  map.addLayer(
    {
      id: ROUTES_HIT,
      type: "line",
      source: ROUTES_SOURCE,
      paint: { "line-color": route, "line-width": hitWidth, "line-opacity": 0 },
    },
    underTrails,
  );

  const underCampsites = before(map, "campsites-point");
  map.addLayer(
    {
      id: SELECTED_CASING,
      type: "line",
      source: SELECTED_SOURCE,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": casing,
        "line-width": numericToken("--map-route-casing-width", 7),
        "line-opacity": 0.8,
      },
    },
    underCampsites,
  );
  map.addLayer(
    {
      id: SELECTED_LINE,
      type: "line",
      source: SELECTED_SOURCE,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": selected,
        "line-width": numericToken("--map-route-selected-width", 4),
      },
    },
    underCampsites,
  );
  map.addLayer(
    {
      id: SELECTED_HIT,
      type: "line",
      source: SELECTED_SOURCE,
      paint: { "line-color": selected, "line-width": hitWidth * 1.5, "line-opacity": 0 },
    },
    underCampsites,
  );
  map.addLayer({
    id: ALONG_POINTS,
    type: "circle",
    source: ALONG_SOURCE,
    paint: {
      "circle-radius": numericToken("--map-campsites-radius", 6),
      "circle-color": campsite,
      "circle-stroke-width": numericToken("--map-campsites-stroke-width", 1.5),
      "circle-stroke-color": stroke,
    },
  });
}

export function removeRouteLayers(map: maplibregl.Map): void {
  for (const id of [ALONG_POINTS, SELECTED_HIT, SELECTED_LINE, SELECTED_CASING, ROUTES_HIT, ROUTES_LINE]) {
    if (map.getLayer(id)) map.removeLayer(id);
  }
  for (const id of [ALONG_SOURCE, SELECTED_SOURCE, ROUTES_SOURCE]) {
    if (map.getSource(id)) map.removeSource(id);
  }
}

/**
 * Whether a click at `point` landed on a named route. Discover's own click handler asks
 * this first, so clicking a route opens the trail panel and not also the popup for the
 * trail segment underneath it.
 */
export function isRouteHit(map: maplibregl.Map, point: maplibregl.PointLike): boolean {
  const layers = [ROUTES_HIT, SELECTED_HIT].filter((id) => map.getLayer(id));
  if (layers.length === 0) return false;
  return map.queryRenderedFeatures(point, { layers }).length > 0;
}
