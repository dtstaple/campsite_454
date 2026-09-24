/**
 * Popup HTML for each clickable layer.
 *
 * Several properties are tri-state per docs/api.md: null means the source did not say,
 * which is different from false. A value the source did not give us is styled as
 * unknown rather than rendered as a fact -- showing a null `perennial` as "Intermittent"
 * would be asserting something we do not know.
 */

import type { LayerName } from "../api";

type Properties = Record<string, unknown> | null;

const TRAIL_TYPES: Record<string, string> = {
  path: "Path",
  footway: "Footway",
  track: "Track",
  bridleway: "Bridleway",
};

/** Label for the Type row, and the noun used when the feature has no name. */
const WATER_TYPES: Record<string, { label: string; noun: string }> = {
  stream: { label: "Stream or river", noun: "stream" },
  lake: { label: "Lake or pond", noun: "lake" },
  wetland: { label: "Wetland", noun: "wetland" },
  spring: { label: "Spring", noun: "spring" },
  other: { label: "Other", noun: "water feature" },
};

const METRES_PER_MILE = 1609.344;

/** Popup HTML for a feature from `layer`. */
export function popupFor(layer: LayerName, properties: Properties): string {
  switch (layer) {
    case "campsites":
      return campsitePopup(properties);
    case "trails":
      return trailPopup(properties);
    case "water":
      return waterPopup(properties);
  }
}

function campsitePopup(properties: Properties): string {
  const siteType = ((properties?.site_type as string) ?? "unknown").replace(/_/g, " ");
  const reservable = properties?.reservable;
  const capacity = properties?.capacity;

  return popup("Campsite", (properties?.name as string) || "Unnamed campsite", [
    row("Type", siteType, siteType === "unknown"),
    row(
      "Reservable",
      reservable === true ? "Yes" : reservable === false ? "No" : "Unknown",
      reservable !== true && reservable !== false,
    ),
    row(
      "Capacity",
      isMissing(capacity) ? "Unknown" : `${capacity} people`,
      isMissing(capacity),
      true,
    ),
  ]);
}

function trailPopup(properties: Properties): string {
  // The model allows any OSM highway value, so an unlisted one is shown as-is rather
  // than hidden behind "Unknown". Only a blank value is genuinely unknown.
  const rawType = (properties?.trail_type as string) || "";
  const trailType = TRAIL_TYPES[rawType] ?? rawType.replace(/_/g, " ");
  const length = properties?.length_m;

  return popup("Trail", (properties?.name as string) || "Unnamed trail", [
    row("Type", trailType || "Unknown", !trailType),
    row(
      "Length",
      typeof length === "number" ? formatLength(length) : "Unknown",
      typeof length !== "number",
      true,
    ),
  ]);
}

function waterPopup(properties: Properties): string {
  const waterType = WATER_TYPES[properties?.feature_type as string];
  const perennial = properties?.perennial;
  const fallbackName = `Unnamed ${waterType?.noun ?? "water feature"}`;

  return popup("Water", (properties?.name as string) || fallbackName, [
    row("Type", waterType?.label ?? "Unknown", !waterType),
    row(
      "Flow",
      perennial === true ? "Year-round" : perennial === false ? "Intermittent" : "Unknown",
      perennial !== true && perennial !== false,
    ),
  ]);
}

/**
 * Metres under a kilometre, otherwise kilometres with miles alongside. The data is
 * metric, but US trail signage and guidebooks give distances in miles.
 */
function formatLength(metres: number): string {
  if (metres < 1000) return `${Math.round(metres)} m`;
  const km = (metres / 1000).toFixed(1);
  const miles = (metres / METRES_PER_MILE).toFixed(1);
  return `${km} km (${miles} mi)`;
}

function isMissing(value: unknown): boolean {
  return value === null || value === undefined;
}

function row(label: string, value: string, unknown: boolean, numeric = false): string {
  const classes = [unknown ? "unknown" : "", numeric && !unknown ? "numeric" : ""]
    .filter(Boolean)
    .join(" ");
  return `<dt>${label}</dt><dd${classes ? ` class="${classes}"` : ""}>${escapeHtml(value)}</dd>`;
}

function popup(eyebrow: string, title: string, rows: string[]): string {
  return `
    <div class="popup">
      <div class="popup-eyebrow">${eyebrow}</div>
      <h3 class="popup-title">${escapeHtml(title)}</h3>
      <dl>
        ${rows.join("\n        ")}
      </dl>
    </div>`;
}

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ]!,
  );
}
