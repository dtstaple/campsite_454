/**
 * Terrain overlays on the map (TM05-142): the pooling-risk and exposure zones, and one
 * campsite's viewshed for "Show what I can see", or a map point's (TM05-151).
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
/** TM05-151: "What can I see from here?" for any map point; its own source, so opening or
 * closing a campsite never clears it, and the other way round. */
export const POINT_VIEWSHED_SOURCE = "terrain-viewshed-point";
const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

function before(map: maplibregl.Map, ids: string[]): string | undefined {
  return ids.find((id) => map.getLayer(id));
}

/** Add both zone overlays and the (empty) viewshed layers. Call once, after addMapLayers. */
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
  addViewshedLayers(map, VIEWSHED_SOURCE);
  addViewshedLayers(map, POINT_VIEWSHED_SOURCE);
}

/** A viewshed source with its pale fill and outline, under the campsite markers. */
function addViewshedLayers(map: maplibregl.Map, sourceId: string): void {
  if (map.getSource(sourceId)) return;
  map.addSource(sourceId, { type: "geojson", data: EMPTY });
  const under = before(map, ["campsites-point"]);
  map.addLayer(
    {
      id: `${sourceId}-fill`,
      type: "fill",
      source: sourceId,
      paint: {
        "fill-color": token("--terrain-viewshed"),
        "fill-opacity": numericToken("--terrain-viewshed-fill-opacity", 0.3),
      },
    },
    under,
  );
  map.addLayer(
    {
      id: `${sourceId}-line`,
      type: "line",
      source: sourceId,
      paint: {
        "line-color": token("--terrain-viewshed"),
        "line-width": numericToken("--terrain-zone-line-width", 1),
      },
    },
    under,
  );
}

/** Draw one viewshed, or clear it with null: a campsite's by default, or a map point's. */
export function showViewshed(
  map: maplibregl.Map,
  feature: Feature | null,
  sourceId: string = VIEWSHED_SOURCE,
): void {
  const source = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined;
  source?.setData(feature ? { type: "FeatureCollection", features: [feature] } : EMPTY);
}
