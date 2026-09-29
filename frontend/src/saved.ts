/**
 * Saving campsites. Contract: docs/auth.md
 *
 * Reads and writes both go to the server, so the list belongs to the account and
 * follows the user between devices. It was a per-browser localStorage record until
 * TM05-32 added `GET /api/saved-campsites/`; this reads from that.
 *
 * The id used throughout is the campsite's `source_id`, the same string the map API
 * puts in each Feature's `id` (see docs/api.md). It is what the save endpoint accepts.
 */

import { authHeaders, type Session } from "./auth";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

/** Enough to draw a row and fly to it without re-querying the API. */
export interface SavedCampsite {
  id: string;
  name: string;
  lon: number;
  lat: number;
}

export class SaveError extends Error {}

/** One row of `GET /api/saved-campsites/`. */
interface SavedCampsiteResponse {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
}

/**
 * The account's saved campsites, from the server.
 *
 * Signed out means an empty list without a request. A failed request also yields an
 * empty list rather than throwing: the saved panel is secondary to the map and should
 * not be able to take the page down, and a save still reports its own errors.
 */
export async function loadSaved(session: Session | null): Promise<SavedCampsite[]> {
  if (!session) return [];
  try {
    const response = await fetch(`${API_BASE_URL}/api/saved-campsites/`, {
      headers: authHeaders(session),
    });
    if (!response.ok) return [];
    const rows = (await response.json()) as SavedCampsiteResponse[];
    // The API names them latitude/longitude; the map wants lon/lat.
    return rows.map((row) => ({
      id: row.id,
      name: row.name,
      lon: row.longitude,
      lat: row.latitude,
    }));
  } catch {
    return [];
  }
}

async function send(method: "POST" | "DELETE", id: string, session: Session) {
  const url = `${API_BASE_URL}/api/saved-campsites/${id}/`;
  let response: Response;
  try {
    response = await fetch(url, { method, headers: authHeaders(session) });
  } catch {
    throw new SaveError(`Could not reach the API at ${API_BASE_URL}.`);
  }

  if (response.status === 401) {
    throw new SaveError("Your session has expired. Sign in again.");
  }
  // DELETE returns 404 both for "no such campsite" and "you had not saved it". The
  // second is the common case and is not worth an error: the user wanted it gone and
  // it is gone.
  if (method === "DELETE" && response.status === 404) return;
  if (!response.ok) {
    throw new SaveError(`Could not ${method === "POST" ? "save" : "unsave"} that campsite.`);
  }
}

/** Save a campsite. Returns the updated list. Idempotent -- a repeat save is a 200. */
export async function save(
  campsite: SavedCampsite,
  session: Session,
  current: SavedCampsite[],
): Promise<SavedCampsite[]> {
  await send("POST", campsite.id, session);
  return current.some((entry) => entry.id === campsite.id)
    ? current
    : [...current, campsite];
}

/** Unsave a campsite. Returns the updated list. */
export async function unsave(
  id: string,
  session: Session,
  current: SavedCampsite[],
): Promise<SavedCampsite[]> {
  await send("DELETE", id, session);
  return current.filter((entry) => entry.id !== id);
}
