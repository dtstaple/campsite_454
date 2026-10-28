/**
 * Client for GET /api/conditions/?lat=&lon= (TM05-120). Contract: docs/api.md,
 * "Conditions". An upstream failure arrives inside the body as a section with status
 * "error"; this only throws when the API itself cannot be reached or rejects the request.
 */

import { API_BASE_URL } from "../api";
import type { Conditions, LatLon } from "./conditions";

export class ConditionsApiError extends Error {}

export async function fetchConditions({ lat, lon }: LatLon, signal?: AbortSignal): Promise<Conditions> {
  const query = new URLSearchParams({ lat: lat.toFixed(5), lon: lon.toFixed(5) });
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/conditions/?${query}`, { signal });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ConditionsApiError(`Could not reach the API at ${API_BASE_URL}.`);
  }
  if (!response.ok) throw new ConditionsApiError(`HTTP ${response.status}`);
  return (await response.json()) as Conditions;
}
