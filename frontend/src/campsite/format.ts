/**
 * Wording for the campsite panel (TM05-66). Feet and miles as in the trail panel; short
 * distances in metres, where feet would be a confusingly large number.
 */

import type { CampsiteDetail } from "./api";

const FT_PER_M = 3.28084;
const M_PER_MI = 1609.344;

export function distance(metres: number): string {
  return metres < 1000 ? `${Math.round(metres)} m` : `${(metres / M_PER_MI).toFixed(1)} mi`;
}

export function elevation(metres: number): string {
  return `${Math.round(metres * FT_PER_M).toLocaleString()} ft`;
}

export function slope(degrees: number, percent: number): string {
  return `${Math.round(degrees)}° (${Math.round(percent)}%)`;
}

export function coordinates(detail: Pick<CampsiteDetail, "lat" | "lon">): string {
  return `${detail.lat.toFixed(5)}, ${detail.lon.toFixed(5)}`;
}

/** OSM tag -> label. Tags not listed are not shown: they are metadata, not amenities. */
export const AMENITY_LABELS: Record<string, string> = {
  operator: "Operator",
  tents: "Tents",
  fireplace: "Fireplace",
  openfire: "Open fire",
  toilets: "Toilets",
  drinking_water: "Drinking water",
  shower: "Shower",
  fee: "Fee",
  access: "Access",
  dog: "Dogs",
  caravans: "Caravans",
  cabins: "Cabins",
  power_supply: "Power",
  opening_hours: "Season",
  wheelchair: "Wheelchair",
  phone: "Phone",
  ref: "Site number",
};

/** "yes" -> "Yes"; anything else as given. */
export function tagValue(value: string): string {
  const lower = value.toLowerCase();
  if (lower === "yes") return "Yes";
  if (lower === "no") return "No";
  return value;
}

export function shelterLabel(kind: string | null): string | null {
  if (kind === "lean-to") return "Lean-to";
  if (kind === "tent site") return "Tent site";
  return null;
}
