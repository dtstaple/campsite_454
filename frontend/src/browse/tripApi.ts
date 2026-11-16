/**
 * POST /api/discover/interpret/ (TM05-170). The server holds any model key; the browser
 * only ever sends the text and gets back the reading.
 */

import { API_BASE_URL } from "../api";
import type { InterpretAnswer } from "./tripReading";

export async function interpretTrip(text: string, signal?: AbortSignal): Promise<InterpretAnswer> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/discover/interpret/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new Error(`Could not reach the API at ${API_BASE_URL}.`);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.error ?? `The server answered ${response.status}.`);
  return body as InterpretAnswer;
}
