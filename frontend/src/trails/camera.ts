/**
 * The 3D trail camera (TM05-62): where to put the camera for a position along a route.
 *
 * MapLibre's camera is described by the point it looks at (`center`) plus `bearing` and
 * `pitch`; with a pitch the eye sits behind and above that point, facing along the
 * bearing. So "behind and above the current position, looking ahead" means: look at a
 * point a little *ahead* of the current position, facing the direction of travel.
 *
 * Direction of travel is the hard part. A trail's own segments swing through every
 * switchback, and a camera that follows them whips left and right. So the bearing comes
 * from a simplified copy of the line (Douglas-Peucker, ~40 m), and is then averaged over a
 * window either side of the position as a circular mean. During playback it is also eased
 * from frame to frame, so it turns rather than snaps.
 */

import { bearing, measure, pointAt, type LngLat, type MeasuredLine } from "./geometry";

const RAD = Math.PI / 180;
const M_PER_DEG_LAT = 111_320;

export interface CameraSettings {
  /** How far ahead of the position the camera looks. */
  lookAheadM: number;
  /** Half-width of the window the bearing is averaged over. */
  bearingWindowM: number;
  /** Douglas-Peucker tolerance for the bearing line. */
  simplifyM: number;
  pitch: number;
  zoom: number;
}

export const CAMERA: CameraSettings = {
  lookAheadM: 120,
  bearingWindowM: 250,
  simplifyM: 40,
  pitch: 68,
  zoom: 14.6,
};

/** Douglas-Peucker in a local metric plane. Keeps the first and last points. */
export function simplify(coords: LngLat[], toleranceM: number): LngLat[] {
  if (coords.length <= 2) return coords.slice();
  const lat0 = coords[0][1] * RAD;
  const toXY = ([lon, lat]: LngLat) => [lon * M_PER_DEG_LAT * Math.cos(lat0), lat * M_PER_DEG_LAT];
  const xy = coords.map(toXY);
  const keep = new Uint8Array(coords.length);
  keep[0] = keep[coords.length - 1] = 1;
  const stack: [number, number][] = [[0, coords.length - 1]];
  while (stack.length) {
    const [first, last] = stack.pop()!;
    const [ax, ay] = xy[first];
    const [bx, by] = xy[last];
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSq = dx * dx + dy * dy;
    let worst = -1;
    let worstDistance = 0;
    for (let i = first + 1; i < last; i++) {
      const [px, py] = xy[i];
      const t = lengthSq ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSq)) : 0;
      const distance = Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
      if (distance > worstDistance) {
        worstDistance = distance;
        worst = i;
      }
    }
    if (worst > 0 && worstDistance > toleranceM) {
      keep[worst] = 1;
      stack.push([first, worst], [worst, last]);
    }
  }
  return coords.filter((_, i) => keep[i]);
}

/** Circular mean of bearings sampled along `line` around `distance`, in degrees. */
export function smoothedBearing(line: MeasuredLine, distance: number, windowM: number): number {
  const steps = 8;
  let x = 0;
  let y = 0;
  for (let k = -steps; k <= steps; k++) {
    const d = distance + (k / steps) * windowM;
    const a = pointAt(line, d - 20);
    const b = pointAt(line, d + 20);
    if (a[0] === b[0] && a[1] === b[1]) continue;
    // Weight the centre more than the edges of the window.
    const weight = 1 - Math.abs(k) / (steps + 1);
    const angle = bearing(a, b) * RAD;
    x += Math.cos(angle) * weight;
    y += Math.sin(angle) * weight;
  }
  return x === 0 && y === 0 ? 0 : ((Math.atan2(y, x) / RAD) + 360) % 360;
}

/** Move `from` toward `to` by `t` (0-1) the short way round the compass. */
export function easeBearing(from: number, to: number, t: number): number {
  const delta = ((to - from + 540) % 360) - 180;
  return (from + delta * t + 360) % 360;
}

export interface TrailCamera {
  center: LngLat;
  bearing: number;
}

/** A camera rig for one route: the full line for position, a simplified one for heading. */
export function rigFor(line: MeasuredLine, settings: CameraSettings = CAMERA) {
  const heading = measure(simplify(line.coords, settings.simplifyM));
  // The simplified line is a little shorter; map distances proportionally onto it.
  const scale = line.length ? heading.length / line.length : 1;
  return {
    heading,
    at(distance: number): TrailCamera {
      return {
        center: pointAt(line, distance + settings.lookAheadM),
        bearing: smoothedBearing(heading, distance * scale, settings.bearingWindowM),
      };
    },
  };
}
