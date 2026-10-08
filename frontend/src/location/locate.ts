/**
 * Where the map opens (TM05-78): the user's location when they share it, the default
 * region when they don't, and an honest message when they are somewhere we have no data.
 *
 * Pure apart from the injected geolocation and storage, so node --test can drive it with
 * a fake of each: inside coverage, outside coverage, denied, unavailable.
 *
 * A denial is remembered (localStorage), so the browser is not asked again on every
 * load; MapLibre's locate button on the map asks again on demand and clears the memory.
 */

import type { Region } from "../regions";

export const DENIED_KEY = "campsite.geolocation";
export const DENIED = "denied";
/** Generous for a phone indoors; the map is already showing the default region meanwhile. */
export const TIMEOUT_MS = 10_000;
/** A fix from the last 10 minutes is as good as a new one for choosing where to open. */
export const MAX_AGE_MS = 10 * 60 * 1000;
/** Close enough to see the trails around you (linework starts at zoom 9). */
export const LOCATED_ZOOM = 12;

export type LngLat = [number, number];

export type StartOutcome =
  /** Inside a covered region: centre on the user. */
  | { kind: "inside"; center: LngLat; region: Region }
  /** Outside every region: centre on the user and say where the data is. */
  | { kind: "outside"; center: LngLat; nearest: Region; distanceKm: number }
  /** Denied, unavailable, timed out, or never asked: stay on the default region. */
  | { kind: "fallback"; reason: "denied" | "remembered-denial" | "unavailable" | "unsupported" };

interface Storage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** The parts of navigator.geolocation this uses. */
export interface Geolocation {
  getCurrentPosition(
    success: (position: { coords: { longitude: number; latitude: number } }) => void,
    error: (error: { code: number }) => void,
    options?: { timeout?: number; maximumAge?: number; enableHighAccuracy?: boolean },
  ): void;
}

/** GeolocationPositionError.PERMISSION_DENIED. */
export const PERMISSION_DENIED = 1;

export function inRegion([lon, lat]: LngLat, region: Region): boolean {
  const [west, south, east, north] = region.bbox;
  return lon >= west && lon <= east && lat >= south && lat <= north;
}

const EARTH_KM = 6371;
const rad = (degrees: number) => (degrees * Math.PI) / 180;

export function haversineKm([lon1, lat1]: LngLat, [lon2, lat2]: LngLat): number {
  const a =
    Math.sin(rad(lat2 - lat1) / 2) ** 2 +
    Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lon2 - lon1) / 2) ** 2;
  return 2 * EARTH_KM * Math.asin(Math.sqrt(a));
}

/** Distance to the nearest edge of a region's box (0 inside it). */
export function distanceToRegionKm(point: LngLat, region: Region): number {
  const [west, south, east, north] = region.bbox;
  const nearest: LngLat = [
    Math.min(Math.max(point[0], west), east),
    Math.min(Math.max(point[1], south), north),
  ];
  return haversineKm(point, nearest);
}

/** What to do with a position. */
export function decide(point: LngLat, regions: readonly Region[]): StartOutcome {
  const inside = regions.find((region) => inRegion(point, region));
  if (inside) return { kind: "inside", center: point, region: inside };
  let nearest = regions[0];
  let distanceKm = distanceToRegionKm(point, nearest);
  for (const region of regions.slice(1)) {
    const d = distanceToRegionKm(point, region);
    if (d < distanceKm) [nearest, distanceKm] = [region, d];
  }
  return { kind: "outside", center: point, nearest, distanceKm };
}

function remembered(storage: Storage | null): boolean {
  try {
    return storage?.getItem(DENIED_KEY) === DENIED;
  } catch {
    return false;
  }
}

/** Forget a remembered denial: the user asked to be located after all. */
export function forgetDenial(storage: Storage | null): void {
  try {
    storage?.removeItem(DENIED_KEY);
  } catch {
    /* Storage unavailable: nothing was remembered. */
  }
}

/**
 * Ask once for the user's position and decide where the map should be. Never rejects:
 * every failure is a fallback to the default region.
 */
export function locateStart(
  geolocation: Geolocation | undefined,
  storage: Storage | null,
  regions: readonly Region[],
): Promise<StartOutcome> {
  if (remembered(storage)) return Promise.resolve({ kind: "fallback", reason: "remembered-denial" });
  if (!geolocation) return Promise.resolve({ kind: "fallback", reason: "unsupported" });
  return new Promise((resolve) => {
    geolocation.getCurrentPosition(
      ({ coords }) => resolve(decide([coords.longitude, coords.latitude], regions)),
      (error) => {
        if (error.code === PERMISSION_DENIED) {
          try {
            storage?.setItem(DENIED_KEY, DENIED);
          } catch {
            /* Can't remember it; the browser itself usually does. */
          }
          resolve({ kind: "fallback", reason: "denied" });
        } else {
          resolve({ kind: "fallback", reason: "unavailable" });
        }
      },
      { timeout: TIMEOUT_MS, maximumAge: MAX_AGE_MS, enableHighAccuracy: false },
    );
  });
}

/** "about 230 km", "about 1,400 km". */
export function aboutKm(km: number): string {
  const rounded = km < 100 ? Math.round(km / 5) * 5 : Math.round(km / 10) * 10;
  return `about ${Math.max(rounded, 5).toLocaleString("en-US")} km`;
}
