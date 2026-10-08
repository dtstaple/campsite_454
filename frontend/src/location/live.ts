/**
 * Live location on the trail (TM05-103): the accuracy circle, and where the hiker is
 * along the open trail. Pure, so node --test checks it.
 */

import { haversineM, locate, pointAt, type LngLat, type MeasuredLine } from "../trails/geometry.ts";

const EARTH_M = 6_371_008.8;
const M_PER_MI = 1609.344;
/** Farther than this from the open trail, the hiker is not "on" it: no mile is shown. */
export const ON_TRAIL_M = 150;

/** A polygon ring approximating a circle of `radiusM` metres around a point. */
export function accuracyCircle([lon, lat]: LngLat, radiusM: number, steps = 48): LngLat[] {
  const ring: LngLat[] = [];
  const latRad = (lat * Math.PI) / 180;
  for (let i = 0; i <= steps; i++) {
    const angle = (2 * Math.PI * i) / steps;
    const dNorth = radiusM * Math.cos(angle);
    const dEast = radiusM * Math.sin(angle);
    ring.push([
      lon + ((dEast / (EARTH_M * Math.cos(latRad))) * 180) / Math.PI,
      lat + ((dNorth / EARTH_M) * 180) / Math.PI,
    ]);
  }
  return ring;
}

/** Where a position is along a trail: metres along it and metres off it. */
export function alongTrail(line: MeasuredLine, position: LngLat): { alongM: number; offM: number } {
  const alongM = locate(line, position);
  return { alongM, offM: haversineM(pointAt(line, alongM), position) };
}

/** "mi 2.3 along Van Hoevenberg Trail", or null when the hiker is off it. */
export function mileLabel(line: MeasuredLine, position: LngLat, trailName: string): string | null {
  const { alongM, offM } = alongTrail(line, position);
  if (offM > ON_TRAIL_M) return null;
  return `mi ${(alongM / M_PER_MI).toFixed(1)} along ${trailName}`;
}
