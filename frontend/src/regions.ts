/**
 * Region shortcuts -- the places the ingest actually put data.
 *
 * These boxes are transcribed from backend/pipeline/regions.yml, which remains the
 * source of truth. They are duplicated rather than fetched because there is no
 * endpoint that serves them and TM05-23 is frontend-only; if a third consumer ever
 * needs them, promote them to a read-only `GET /api/regions/` and delete this file.
 *
 * Duplication is tolerable here because drift is loud rather than silent: a stale box
 * flies the map somewhere empty, which is obvious on the first click. It is also worth
 * noting that regions.yml calls its boxes "deliberately approximate" ingestion extents
 * rather than display geometry, so a viewport shortcut was never going to consume them
 * unmodified -- see regionCamera() below.
 *
 * Only the two ingested regions are listed. Green Mountains VT and Maine are defined in
 * regions.yml but hold no data yet, and a shortcut to either would land the user on the
 * blank map this story exists to prevent. When one is ingested, add it here.
 */

import type * as maplibregl from "maplibre-gl";
import { MIN_ZOOM_FOR_LINEWORK, type Bbox } from "./api";

export interface Region {
  /** Matches the key in backend/pipeline/regions.yml. */
  id: string;
  label: string;
  bbox: Bbox;
}

export const REGIONS: readonly Region[] = [
  { id: "adirondacks", label: "Adirondacks", bbox: [-75.4, 43.0, -73.3, 44.9] },
  { id: "white-mountains-nh", label: "White Mountains", bbox: [-72.0, 43.85, -70.95, 44.55] },
];

/**
 * Where the map opens.
 *
 * The Adirondacks hold the overwhelming bulk of the ingested data -- roughly 63,000
 * water features and 18,000 trails (down from 26,000 once TM05-26 filtered out
 * sidewalks, crossings and road imports). They also have campsites now: Recreation.gov
 * is federal only and returns none here, but the OpenStreetMap source added in TM05-27
 * covers the state land, so all four layers draw on the opening view.
 */
export const DEFAULT_REGION = REGIONS[0];
export const DEFAULT_ZOOM = 10;

/**
 * The lowest zoom a region shortcut is allowed to land on.
 *
 * Fitting the Adirondack box exactly (2.1 x 1.9 degrees) settles at roughly z8, below
 * MIN_ZOOM_FOR_LINEWORK, so arriving there would hide water and trails the instant the
 * user got there -- precisely the dead end these shortcuts exist to escape. Clamping up
 * trades a little of the region's edges for a view that has something in it.
 */
export const MIN_REGION_ZOOM = MIN_ZOOM_FOR_LINEWORK + 0.5;

/** Geographic centre of a bbox, used as the fallback fly target. */
export function bboxCenter([west, south, east, north]: Bbox): [number, number] {
  return [(west + east) / 2, (south + north) / 2];
}

/**
 * Where a shortcut to `region` should land: the box fitted to the current viewport,
 * then clamped up to MIN_REGION_ZOOM. cameraForBounds can return undefined when the
 * container has no size yet, so the centre at the minimum zoom is the fallback.
 */
export function regionCamera(
  map: maplibregl.Map,
  region: Region,
): { center: maplibregl.LngLatLike; zoom: number } {
  const [west, south, east, north] = region.bbox;
  const fitted = map.cameraForBounds([
    [west, south],
    [east, north],
  ]);
  return {
    center: fitted?.center ?? bboxCenter(region.bbox),
    zoom: Math.max(fitted?.zoom ?? MIN_REGION_ZOOM, MIN_REGION_ZOOM),
  };
}

/**
 * The region whose box contains this point, if any -- which is how the panel knows
 * which shortcut is "current". The boxes do not overlap, so there is at most one.
 */
export function regionAt([lon, lat]: [number, number]): Region | undefined {
  return REGIONS.find(
    ({ bbox: [west, south, east, north] }) =>
      lon >= west && lon <= east && lat >= south && lat <= north,
  );
}
