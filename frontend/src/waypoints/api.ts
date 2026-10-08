/**
 * The signed-in user's waypoints (TM05-80). Contract: docs/api.md, "Custom waypoints".
 */

import { authHeaders, type Session } from "../auth";
import type { WaypointKind } from "./kinds";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export interface Waypoint {
  id: number;
  name: string;
  kind: WaypointKind;
  kind_label: string;
  note: string;
  lon: number;
  lat: number;
}

export type WaypointFields = Pick<Waypoint, "name" | "kind" | "note" | "lon" | "lat">;

export class WaypointError extends Error {}

async function request<T>(session: Session, path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...authHeaders(session), ...init.headers },
    });
  } catch {
    throw new WaypointError(`Could not reach the API at ${API_BASE_URL}.`);
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      body?.error ??
      (body && typeof body === "object"
        ? Object.values(body).flat().join(" ")
        : `The server answered ${response.status}.`);
    throw new WaypointError(String(message));
  }
  return body as T;
}

export function listWaypoints(session: Session) {
  return request<Waypoint[]>(session, "/api/waypoints/");
}

export function createWaypoint(session: Session, fields: WaypointFields) {
  return request<Waypoint>(session, "/api/waypoints/", {
    method: "POST",
    body: JSON.stringify(fields),
  });
}

export function updateWaypoint(session: Session, id: number, fields: Partial<WaypointFields>) {
  return request<Waypoint>(session, `/api/waypoints/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
}

export function deleteWaypoint(session: Session, id: number) {
  return request<void>(session, `/api/waypoints/${id}/`, { method: "DELETE" });
}
