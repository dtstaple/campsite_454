/**
 * The two terrain overlays (TM05-142) as data: "Water pooling risk" and "Exposure".
 * Each is a vector tile layer of zone polygons from the terrain pipeline (TM05-141),
 * served by /api/tiles/<layer>/{z}/{x}/{y}.mvt. Pure, so node --test can load it;
 * zonesLayer.ts adds them to the map.
 */

export type ZoneOverlay = "pooling-risk" | "exposure";

export interface ZoneSpec {
  id: ZoneOverlay;
  label: string;
  /** The legend's one line. */
  legend: string;
  /** theme.css tokens: fill colour, its opacity, and the outline colour. */
  token: string;
  /** Matches the backend TileLayer's minzoom; below it the server has nothing. */
  minzoom: number;
}

export const ZONE_MAX_ZOOM = 14;

export const ZONES: readonly ZoneSpec[] = [
  {
    id: "pooling-risk",
    label: "Water pooling risk",
    legend: "High: low ground that water drains into",
    token: "--terrain-pooling",
    minzoom: 8,
  },
  {
    id: "exposure",
    label: "Exposure",
    legend: "High: ground that stands above its surroundings, open to wind",
    token: "--terrain-exposure",
    minzoom: 8,
  },
];

export function zoneSource(apiBase: string, zone: ZoneSpec) {
  return {
    type: "vector" as const,
    tiles: [`${apiBase}/api/tiles/${zone.id}/{z}/{x}/{y}.mvt`],
    minzoom: zone.minzoom,
    maxzoom: ZONE_MAX_ZOOM,
  };
}

/** Draw-layer ids for a zone overlay: a fill and an outline. */
export function zoneLayerIds(zone: ZoneOverlay): [string, string] {
  return [`terrain-${zone}-fill`, `terrain-${zone}-line`];
}

/** The two map methods a toggle needs, so the toggle can be tested without MapLibre. */
export interface ToggleTarget {
  getLayer(id: string): unknown;
  setLayoutProperty(layer: string, name: "visibility", value: "visible" | "none"): unknown;
}

/** Show or hide one zone overlay's fill and outline. */
export function setZoneVisible(map: ToggleTarget, zone: ZoneOverlay, on: boolean): void {
  for (const id of zoneLayerIds(zone)) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  }
}
