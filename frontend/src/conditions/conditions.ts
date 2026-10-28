/**
 * Conditions (TM05-120): the short forecast and active NWS alerts for a point, as
 * GET /api/conditions/ returns them. Contract: docs/api.md, "Conditions". Wording and
 * units live here, apart from the component, so the tests can check them.
 *
 * The API speaks metric (°C, mm, km/h); the panels speak imperial, like the trail stats.
 */

export interface ForecastDay {
  date: string;
  temperature_min_c: number | null;
  temperature_max_c: number | null;
  precipitation_mm: number | null;
  precipitation_probability_pct: number | null;
  wind_max_kmh: number | null;
  gust_max_kmh: number | null;
}

export interface WeatherAlert {
  id: string;
  event: string;
  headline: string | null;
  severity: string;
  urgency: string | null;
  certainty: string | null;
  effective: string | null;
  onset: string | null;
  expires: string | null;
  ends: string | null;
  sender_name: string | null;
  area: string | null;
  description: string | null;
  instruction: string | null;
}

interface Source {
  source: string;
  source_url: string;
}

interface Fetched {
  status: "ok";
  fetched_at: string;
  expires_at: string;
  cached: boolean;
}

interface Failed {
  status: "error";
  message: string;
}

export type ForecastSection = Source & ((Fetched & { timezone: string | null; days: ForecastDay[] }) | Failed);
export type AlertsSection = Source & ((Fetched & { items: WeatherAlert[] }) | Failed);

export interface Conditions {
  location: { lat: number; lon: number };
  forecast: ForecastSection;
  alerts: AlertsSection;
}

export interface LatLon {
  lat: number;
  lon: number;
}

/** Where a trail's conditions are fetched for: the middle vertex of its line. */
export function trailPoint(coordinates: readonly (readonly number[])[]): LatLon | null {
  if (coordinates.length === 0) return null;
  const [lon, lat] = coordinates[Math.floor(coordinates.length / 2)];
  return { lat, lon };
}

const fahrenheit = (c: number) => Math.round((c * 9) / 5 + 32);
const mph = (kmh: number) => Math.round(kmh / 1.609344);
const inches = (mm: number) => mm / 25.4;

/** "Today", "Tomorrow", then the weekday: "Thu". Dates are the forecast's local days. */
export function dayLabel(date: string, index: number): string {
  if (index === 0) return "Today";
  if (index === 1) return "Tomorrow";
  // Noon UTC, so no timezone can move the date to a neighbouring day.
  return new Date(`${date}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
}

/** "54° / 38°F", or the half that is known. */
export function temperatureText(day: ForecastDay): string {
  const { temperature_max_c: high, temperature_min_c: low } = day;
  if (high == null && low == null) return "—";
  if (high == null) return `low ${fahrenheit(low!)}°F`;
  if (low == null) return `high ${fahrenheit(high)}°F`;
  return `${fahrenheit(high)}° / ${fahrenheit(low)}°F`;
}

/** "40% rain, 0.12 in" or "Dry". A trace under 0.01 in reads as dry. */
export function precipitationText(day: ForecastDay): string {
  const amount = day.precipitation_mm ?? 0;
  const chance = day.precipitation_probability_pct;
  const rain = inches(amount);
  if (rain < 0.01) return chance ? `Dry (${chance}% chance)` : "Dry";
  const total = `${rain.toFixed(2)} in`;
  return chance != null ? `${chance}% rain, ${total}` : `Rain, ${total}`;
}

/** "Wind 9 mph, gusts 21". */
export function windText(day: ForecastDay): string | null {
  if (day.wind_max_kmh == null) return null;
  const gust = day.gust_max_kmh != null ? `, gusts ${mph(day.gust_max_kmh)}` : "";
  return `Wind ${mph(day.wind_max_kmh)} mph${gust}`;
}

/** Extreme and Severe stand out; advisories and statements are highlighted less. */
export function alertTone(severity: string): "severe" | "moderate" {
  return severity === "Extreme" || severity === "Severe" ? "severe" : "moderate";
}

/** "until Tue 9:00 AM", from the alert's end, else its expiry; null if it gives neither. */
export function alertUntil(alert: WeatherAlert): string | null {
  const end = alert.ends ?? alert.expires;
  if (!end) return null;
  const when = new Date(end);
  if (Number.isNaN(when.getTime())) return null;
  return `until ${when.toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit" })}`;
}

/** "fetched just now", "fetched 12 min ago", or the clock time once it is over an hour. */
export function fetchedText(fetchedAt: string, now: Date = new Date()): string {
  const when = new Date(fetchedAt);
  const minutes = Math.floor((now.getTime() - when.getTime()) / 60_000);
  if (minutes < 1) return "fetched just now";
  if (minutes < 60) return `fetched ${minutes} min ago`;
  return `fetched ${when.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
}

/** The provenance line under a section: "Open-Meteo · fetched 4 min ago". */
export function sourceText(section: ForecastSection | AlertsSection, now: Date = new Date()): string {
  return section.status === "ok" ? `${section.source} · ${fetchedText(section.fetched_at, now)}` : section.source;
}
