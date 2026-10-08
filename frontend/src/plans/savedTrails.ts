/**
 * Saved trails (TM05-100). Contract: docs/api.md, "Saved trails".
 */

import { authHeaders, type Session } from "../auth";
import type { TrailRef } from "./api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export interface SavedTrail {
  id: number;
  osm_id: number | null;
  from_way: string | null;
  name: string;
  length_m: number | null;
}

async function request<T>(session: Session, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeaders(session) },
  });
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.error ?? body?.detail ?? `The server answered ${response.status}.`);
  return body as T;
}

export function listSavedTrails(session: Session) {
  return request<SavedTrail[]>(session, "/api/saved-trails/");
}

export function saveTrail(session: Session, trail: TrailRef) {
  return request<SavedTrail>(session, "/api/saved-trails/", {
    method: "POST",
    body: JSON.stringify(trail),
  });
}

export function unsaveTrail(session: Session, id: number) {
  return request<void>(session, `/api/saved-trails/${id}/`, { method: "DELETE" });
}
