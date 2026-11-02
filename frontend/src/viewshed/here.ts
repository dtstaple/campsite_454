/**
 * "What can I see from here?" (TM05-151): the viewshed from any point on the map, from
 * GET /api/viewshed/?lat=&lon= (docs/api.md, "Viewshed from any point").
 *
 * Pure, so node --test can load it: the request, what each failure tells the user, and the
 * long-press timing. ViewHere.tsx puts it on the map.
 */

import type { Feature, MultiPolygon } from "geojson";

export interface ViewshedProps {
  observer: { lat: number; lon: number };
  region: string;
  radius_m: number;
  eye_height_m: number;
  resolution_m: number;
  area_km2: number;
  direction: string | null;
  /** "About 7.1 km² visible within 10 km, mostly to the east." */
  summary: string;
  /** "Bare-earth elevation" */
  label: string;
  /** The longer caveat: trees, buildings and recent changes aren't counted. */
  note: string;
  cached: boolean;
  computed_at: string;
}

/** The geometry is null when the ground closes in all around. */
export type PointViewshed = Feature<MultiPolygon | null, ViewshedProps>;

export const MENU_LABEL = "What can I see from here?";

/** How long a finger must rest, and how far it may drift, before a press is a long press. */
export const LONG_PRESS_MS = 550;
export const LONG_PRESS_MOVE_PX = 10;

export function viewshedUrl(apiBase: string, lat: number, lon: number): string {
  // Six places is ~0.1 m: plenty, and the server snaps to its cache grid anyway.
  return `${apiBase}/api/viewshed/?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}`;
}

export class ViewshedError extends Error {}

/** What a failed request tells the user: the server's own reason where it gives one. */
export function errorMessage(status: number, body: unknown): string {
  const reason =
    body && typeof body === "object" && "error" in body && typeof body.error === "string"
      ? body.error
      : null;
  if (status === 503) {
    return reason
      ? `Can't work out the view here right now. ${reason}`
      : "Can't work out the view here right now: the terrain model isn't available.";
  }
  if (status === 422 || status === 400) return reason ?? "Can't work out the view from that point.";
  return `Something went wrong working out the view (HTTP ${status}). Try again.`;
}

export async function fetchPointViewshed(
  apiBase: string,
  lat: number,
  lon: number,
  signal?: AbortSignal,
): Promise<PointViewshed> {
  let response: Response;
  try {
    response = await fetch(viewshedUrl(apiBase, lat, lon), { signal });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ViewshedError("Couldn't reach the server. Check your connection and try again.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ViewshedError(errorMessage(response.status, body));
  }
  return (await response.json()) as PointViewshed;
}

/** "44.15020, -73.95020", for the panel's heading. */
export function placeLabel(lat: number, lon: number): string {
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
}

/**
 * Long-press detection for touch, without timers of its own so it can be tested: the
 * component calls start/move/end and runs `fire` when `due()` says so. A second finger,
 * a drag beyond LONG_PRESS_MOVE_PX, or lifting early cancels it.
 */
export class LongPress {
  private origin: { x: number; y: number } | null = null;
  private startedAt = 0;

  start(x: number, y: number, now: number, touches = 1): void {
    this.origin = touches === 1 ? { x, y } : null;
    this.startedAt = now;
  }

  move(x: number, y: number, touches = 1): void {
    if (!this.origin) return;
    if (touches !== 1 || Math.hypot(x - this.origin.x, y - this.origin.y) > LONG_PRESS_MOVE_PX) {
      this.origin = null;
    }
  }

  cancel(): void {
    this.origin = null;
  }

  /** True once, when the press has been held long enough; it then resets. */
  due(now: number): boolean {
    if (!this.origin || now - this.startedAt < LONG_PRESS_MS) return false;
    this.origin = null;
    return true;
  }
}
