/**
 * Terrain overlays on the map (TM05-142): the pooling-risk and exposure zones, and one
 * campsite's viewshed for "Show what I can see".
 *
 * Zones go above public land and under water, trails and campsites: they describe the
 * ground those sit on. The viewshed sits under the campsite markers. Colours come from
 * theme.css (--terrain-*). Each zone is a translucent fill with a solid outline, which
 * reads on the dark basemap and on satellite imagery alike.
 */

import type * as maplibregl from "maplibre-gl";
import type { FeatureCollection, Feature } from "geojson";
import { API_BASE_URL } from "../api";
import { numericToken, token } from "../theme";
import { ZONES, zoneLayerIds, zoneSource, type ZoneOverlay } from "./zones";

export const VIEWSHED_SOURCE = "terrain-viewshed";
const VIEWSHED_FILL = "terrain-viewshed-fill";
const VIEWSHED_LINE = "terrain-viewshed-line";
const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

function before(map: maplibregl.Map, ids: string[]): string | undefined {
  return ids.find((id) => map.getLayer(id));
}

/** Add both zone overlays and the (empty) viewshed layer. Call once, after addMapLayers. */
export function addTerrainOverlays(
  map: maplibregl.Map,
  visible: Record<ZoneOverlay, boolean>,
): void {
  for (const zone of ZONES) {
    if (map.getSource(zone.id)) continue;
    map.addSource(zone.id, zoneSource(API_BASE_URL, zone));
    const [fill, line] = zoneLayerIds(zone.id);
    const colour = token(zone.token);
    const visibility = visible[zone.id] ? "visible" : "none";
    const under = before(map, ["water-fill", "water-line", "trails-line", "campsites-point"]);
    map.addLayer(
      {
        id: fill,
        type: "fill",
        source: zone.id,
        "source-layer": zone.id,
        minzoom: zone.minzoom,
        layout: { visibility },
        paint: {
          "fill-color": colour,
          "fill-opacity": numericToken(`${zone.token}-fill-opacity`, 0.35),
        },
      },
      under,
    );
    map.addLayer(
      {
        id: line,
        type: "line",
        source: zone.id,
        "source-layer": zone.id,
        minzoom: zone.minzoom,
        layout: { visibility },
        paint: {
          "line-color": colour,
          "line-width": numericToken("--terrain-zone-line-width", 1),
          "line-opacity": numericToken("--terrain-zone-line-opacity", 0.9),
        },
      },
      under,
    );
  }
  if (!map.getSource(VIEWSHED_SOURCE)) {
    map.addSource(VIEWSHED_SOURCE, { type: "geojson", data: EMPTY });
    const under = before(map, ["campsites-point"]);
    map.addLayer(
      {
        id: VIEWSHED_FILL,
        type: "fill",
        source: VIEWSHED_SOURCE,
        paint: {
          "fill-color": token("--terrain-viewshed"),
          "fill-opacity": numericToken("--terrain-viewshed-fill-opacity", 0.3),
        },
      },
      under,
    );
    map.addLayer(
      {
        id: VIEWSHED_LINE,
        type: "line",
        source: VIEWSHED_SOURCE,
        paint: {
          "line-color": token("--terrain-viewshed"),
          "line-width": numericToken("--terrain-zone-line-width", 1),
        },
      },
      under,
    );
  }
}

/** Draw one campsite's viewshed, or clear it with null. */
export function showViewshed(map: maplibregl.Map, feature: Feature | null): void {
  const source = map.getSource(VIEWSHED_SOURCE) as maplibregl.GeoJSONSource | undefined;
  source?.setData(feature ? { type: "FeatureCollection", features: [feature] } : EMPTY);
}
