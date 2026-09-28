/**
 * Saving campsites. Contract: docs/auth.md
 *
 * Writes go to the server and are authoritative. Reads do not, and cannot yet:
 *
 *     TODO(TM05-32): there is no `GET /api/saved-campsites/`. The accounts API has
 *     POST and DELETE only, so a signed-in user's saved campsites cannot be fetched.
 *     Until that story lands, the list below is a local record of what *this browser*
 *     saved, which means it is empty on a second device and after clearing site data,
 *     and it does not reflect a save made anywhere else. When the endpoint exists,
 *     `loadSaved()` should fetch it and this cache should become a rendering detail
 *     rather than the source of truth. Do not build features that assume it is
 *     complete.
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

/** Namespaced per user, so two accounts on one browser do not see each other's list. */
function storageKey(username: string): string {
  return `campsite.saved.${username}`;
}

export function loadSaved(session: Session | null): SavedCampsite[] {
  // TODO(TM05-32): replace with GET /api/saved-campsites/ once it exists.
  if (!session) return [];
  try {
    const raw = localStorage.getItem(storageKey(session.username));
    return raw ? (JSON.parse(raw) as SavedCampsite[]) : [];
  } catch {
    // Unreadable or unparseable: an empty list is the honest answer, and it is about
    // to be overwritten by the next save anyway.
    return [];
  }
}

function persist(session: Session, campsites: SavedCampsite[]) {
  try {
    localStorage.setItem(storageKey(session.username), JSON.stringify(campsites));
  } catch {
    /* Storage unavailable: the list still works for this page's lifetime. */
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
  const next = current.some((entry) => entry.id === campsite.id)
    ? current
    : [...current, campsite];
  persist(session, next);
  return next;
}

/** Unsave a campsite. Returns the updated list. */
export async function unsave(
  id: string,
  session: Session,
  current: SavedCampsite[],
): Promise<SavedCampsite[]> {
  await send("DELETE", id, session);
  const next = current.filter((entry) => entry.id !== id);
  persist(session, next);
  return next;
}
