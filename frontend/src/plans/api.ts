/**
 * Overnight plans (TM05-81). Contract: docs/api.md, "Overnight plans".
 */

import { authHeaders, type Session } from "../auth";
import type { Legality } from "../campsite/legality";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

/** Which trail a plan is along: a route by relation id, or an assembled trail by way. */
export type TrailRef = { osm_id: number } | { from_way: string };

export interface PlanStop {
  night: number;
  id: string;
  display_name: string | null;
  display_name_derived: boolean;
  lon: number;
  lat: number;
  distance_along_m: number;
  distance_from_route_m: number;
  score: number | null;
  legality: Legality;
  /** Set unless the verdict is "permitted". */
  warning: string | null;
}

export interface PlanDay {
  day: number;
  from: string;
  to: string;
  start_m: number;
  end_m: number;
  distance_m: number;
  /** Null when the route has no elevation profile. */
  gain_m: number | null;
  loss_m: number | null;
}

export interface WorkedPlan {
  trail: { osm_id: number | null; source_id: string; name: string; length_m: number };
  nights: number;
  stops: PlanStop[];
  days: PlanDay[];
  totals: { distance_m: number; gain_m: number | null; loss_m: number | null };
  profile: { status: "ok" | "unavailable"; reason: string | null };
  warnings: string[];
}

export interface PlanSummary {
  id: number;
  name: string;
  osm_id: number | null;
  from_way: string | null;
  trail_name: string;
  nights?: number;
  updated_at: string;
}

export type SavedPlan = PlanSummary & WorkedPlan;

export class PlanError extends Error {}

async function request<T>(session: Session, path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...authHeaders(session), ...init.headers },
    });
  } catch {
    throw new PlanError(`Could not reach the API at ${API_BASE_URL}.`);
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new PlanError(body?.error ?? body?.detail ?? `The server answered ${response.status}.`);
  }
  return body as T;
}

export function previewPlan(session: Session, trail: TrailRef, stopIds: string[]) {
  return request<WorkedPlan>(session, "/api/plans/preview/", {
    method: "POST",
    body: JSON.stringify({ ...trail, stop_ids: stopIds }),
  });
}

export function listPlans(session: Session, trail?: TrailRef) {
  const query = trail ? `?${new URLSearchParams(Object.entries(trail).map(([k, v]) => [k, String(v)]))}` : "";
  return request<PlanSummary[]>(session, `/api/plans/${query}`);
}

export function getPlan(session: Session, id: number) {
  return request<SavedPlan>(session, `/api/plans/${id}/`);
}

export function createPlan(session: Session, trail: TrailRef, stopIds: string[], name: string) {
  return request<SavedPlan>(session, "/api/plans/", {
    method: "POST",
    body: JSON.stringify({ ...trail, stop_ids: stopIds, name }),
  });
}

export function updatePlan(session: Session, id: number, stopIds: string[], name: string) {
  return request<SavedPlan>(session, `/api/plans/${id}/`, {
    method: "PATCH",
    body: JSON.stringify({ stop_ids: stopIds, name }),
  });
}

export function deletePlan(session: Session, id: number) {
  return request<void>(session, `/api/plans/${id}/`, { method: "DELETE" });
}

/** Save the plan's GPX (track, stops, the user's nearby waypoints) as a file. */
export async function downloadPlanGpx(session: Session, id: number, filename: string) {
  const response = await fetch(`${API_BASE_URL}/api/plans/${id}/gpx/`, {
    headers: authHeaders(session),
  }).catch(() => {
    throw new PlanError(`Could not reach the API at ${API_BASE_URL}.`);
  });
  if (!response.ok) throw new PlanError(`The server answered ${response.status}.`);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await response.blob());
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
