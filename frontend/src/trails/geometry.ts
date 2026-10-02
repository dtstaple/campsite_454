/**
 * Positions along a route line, in metres, computed client-side so hover feedback never
 * waits on the network.
 *
 * Distances use the haversine formula per segment. Over an 11 km route that agrees with
 * the server's EPSG:5070 length to well under 1%, which is far below what a cursor on a
 * 300 px chart can resolve.
 */

export type LngLat = [number, number];

const EARTH_RADIUS_M = 6_371_008.8;
const RAD = Math.PI / 180;

export function haversineM([lon1, lat1]: LngLat, [lon2, lat2]: LngLat): number {
  const dLat = (lat2 - lat1) * RAD;
  const dLon = (lon2 - lon1) * RAD;
  const a =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
}

export interface MeasuredLine {
  coords: LngLat[];
  /** cumulative[i] = metres from the start to coords[i]. */
  cumulative: number[];
  length: number;
}

export function measure(coords: LngLat[]): MeasuredLine {
  const cumulative = [0];
  for (let i = 1; i < coords.length; i++) {
    cumulative.push(cumulative[i - 1] + haversineM(coords[i - 1], coords[i]));
  }
  return { coords, cumulative, length: cumulative[cumulative.length - 1] ?? 0 };
}

/** The point `distance` metres along the line, clamped to its ends. */
export function pointAt(line: MeasuredLine, distance: number): LngLat {
  const { coords, cumulative } = line;
  if (coords.length === 0) return [0, 0];
  if (distance <= 0) return coords[0];
  if (distance >= line.length) return coords[coords.length - 1];
  let lo = 0;
  let hi = cumulative.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (cumulative[mid] <= distance) lo = mid;
    else hi = mid;
  }
  const span = cumulative[hi] - cumulative[lo] || 1;
  const t = (distance - cumulative[lo]) / span;
  const [x1, y1] = coords[lo];
  const [x2, y2] = coords[hi];
  return [x1 + (x2 - x1) * t, y1 + (y2 - y1) * t];
}

/**
 * How far along the line the point nearest `target` is, in metres. Projects onto each
 * segment in a local equirectangular plane, which is exact enough at segment scale.
 */
export function locate(line: MeasuredLine, target: LngLat): number {
  const { coords, cumulative } = line;
  const kx = Math.cos(target[1] * RAD);
  let best = Infinity;
  let along = 0;
  for (let i = 1; i < coords.length; i++) {
    const [ax, ay] = coords[i - 1];
    const [bx, by] = coords[i];
    const dx = (bx - ax) * kx;
    const dy = by - ay;
    const px = (target[0] - ax) * kx;
    const py = target[1] - ay;
    const lengthSq = dx * dx + dy * dy;
    const t = lengthSq ? Math.max(0, Math.min(1, (px * dx + py * dy) / lengthSq)) : 0;
    const ex = px - t * dx;
    const ey = py - t * dy;
    const distanceSq = ex * ex + ey * ey;
    if (distanceSq < best) {
      best = distanceSq;
      along = cumulative[i - 1] + t * (cumulative[i] - cumulative[i - 1]);
    }
  }
  return along;
}

/** Compass bearing in degrees from `a` to `b`. */
export function bearing([lon1, lat1]: LngLat, [lon2, lat2]: LngLat): number {
  const y = Math.sin((lon2 - lon1) * RAD) * Math.cos(lat2 * RAD);
  const x =
    Math.cos(lat1 * RAD) * Math.sin(lat2 * RAD) -
    Math.sin(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.cos((lon2 - lon1) * RAD);
  return (Math.atan2(y, x) / RAD + 360) % 360;
}
