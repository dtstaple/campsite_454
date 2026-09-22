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
 * blank map this story exists to prevent.
 */

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
 * water features and 26,000 trails against a national view that shows nothing at all.
 * Campsites are the exception: that data comes from Recreation.gov, which is federal
 * only, so the Adirondacks return zero and the panel will say so. The White Mountains
 * shortcut is one click away for those.
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
