/**
 * Tile maths for the satellite inset (TM05-66): which Esri tiles cover a box of
 * `width` x `height` CSS pixels centred on a point, and where each one sits.
 */

import { IMAGERY_TILES } from "../basemap/satellite";

export const INSET_ZOOM = 17; // ~1.1 m per pixel at 44 N: the clearing and the shoreline
const TILE = 256;

export interface InsetTile {
  url: string;
  left: number;
  top: number;
}

/** Web Mercator world pixel of a lon/lat at `zoom`. */
export function worldPixel(lon: number, lat: number, zoom: number): [number, number] {
  const size = TILE * 2 ** zoom;
  const x = ((lon + 180) / 360) * size;
  const sin = Math.sin((lat * Math.PI) / 180);
  const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size;
  return [x, y];
}

export function insetTiles(
  lon: number,
  lat: number,
  width: number,
  height: number,
  zoom = INSET_ZOOM,
): InsetTile[] {
  const [cx, cy] = worldPixel(lon, lat, zoom);
  const left = cx - width / 2;
  const top = cy - height / 2;
  const tiles: InsetTile[] = [];
  for (let tx = Math.floor(left / TILE); tx <= Math.floor((left + width) / TILE); tx++) {
    for (let ty = Math.floor(top / TILE); ty <= Math.floor((top + height) / TILE); ty++) {
      tiles.push({
        // {z}/{y}/{x}: Esri puts the row first.
        url: IMAGERY_TILES.replace("{z}", String(zoom)).replace("{y}", String(ty)).replace("{x}", String(tx)),
        left: Math.round(tx * TILE - left),
        top: Math.round(ty * TILE - top),
      });
    }
  }
  return tiles;
}
