/**
 * Terrain facts as words (TM05-142): the campsite panel's Terrain section and the compact
 * badges on Find campsites rows. Pure, so node --test can load it.
 *
 * The facts come from the terrain pipeline (TM05-141, docs/terrain-analysis.md) through
 * the campsite detail's `terrain` block and each campsite row's `terrain` badges. Each
 * fact can be unknown on its own, so every line is optional. A site with no terrain
 * facts gets no section at all.
 */

export type PoolingLevel = "low" | "medium" | "high";
export type ShelterLevel = "sheltered" | "moderate" | "exposed";
/** TM05-147: how much cold air settles at the site on calm nights. */
export type ColdAirLevel = "low" | "medium" | "high";

export interface TerrainPayload {
  pooling: { level: PoolingLevel; reason: string } | null;
  sun: { facing: string; label: string } | null;
  shelter: { level: ShelterLevel; reason: string } | null;
  /** TM05-147; absent from a payload older than the cold-air tool. */
  cold_air?: { level: ColdAirLevel; reason: string } | null;
  /**
   * TM05-148: exposure to the region's prevailing wind, with the direction assumed:
   * `from_deg` is the compass bearing it blows from, `from` its 8-point name.
   */
  wind?: { level: ShelterLevel; reason: string; from_deg: number | null; from: string | null } | null;
  /**
   * TM05-162: direct sun on a June-August day from terrain shade alone; absent from a
   * payload older than the sun tool. Either half can be unknown on its own.
   */
  sun_hours?: SunHours | null;
  view: { area_km2: number | null; direction: string | null; water: boolean | null } | null;
  has_viewshed: boolean;
  note: string;
}

/** TM05-162: full (12 h or more of direct sun), partial (8 h or more) or low. */
export type SunHoursLevel = "full" | "partial" | "low";

export interface SunHours {
  hours: number | null;
  level: SunHoursLevel | null;
  reason: string | null;
  morning_sun: boolean | null;
  morning_reason: string | null;
  /** What the estimate leaves out: trees. */
  estimate: string;
}

/** The compact form on list rows: only what a badge needs. */
export interface TerrainBadges {
  pooling: PoolingLevel | null;
  shelter: ShelterLevel | null;
  water_view: boolean | null;
}

export interface TerrainLine {
  key: "pooling" | "sun" | "shelter" | "cold_air" | "wind" | "sun_hours" | "view";
  label: string;
  value: string;
  detail: string | null;
  /** For styling: a pooling, shelter or cold-air level. */
  tone: string | null;
  /** What kind of estimate the line is, shown under it, e.g. "Terrain estimate". */
  estimate?: string;
}

/** TM05-147: the cold-air line's estimate label. */
export const COLD_AIR_ESTIMATE = "Terrain estimate: where the ground sits among its surroundings, not a measurement";

/** Shown under the section whenever it is. */
export const TERRAIN_NOTE =
  "Terrain-model estimate from bare-earth elevation. Trees, buildings and recent changes aren't counted.";

const SHELTER_WORDS: Record<ShelterLevel, string> = {
  sheltered: "Sheltered",
  moderate: "Moderate shelter",
  exposed: "Exposed",
};

const WIND_WORDS: Record<ShelterLevel, string> = {
  sheltered: "Wind-sheltered",
  moderate: "Moderate",
  exposed: "Exposed",
};

/**
 * TM05-148: the wind line's estimate label, naming the direction it assumes:
 * "Estimate, assuming the prevailing wind is from the west (270°)".
 */
export function windEstimate(wind: NonNullable<TerrainPayload["wind"]>): string {
  if (wind.from_deg === null) return "Estimate, for the region's prevailing wind";
  const name = wind.from ? `the ${wind.from} ` : "";
  return `Estimate, assuming the prevailing wind is from ${name}(${Math.round(wind.from_deg)}°)`;
}

/** "4.2 km²", "0.35 km²" or "12 km²". */
export function area(km2: number): string {
  if (km2 >= 10) return `${Math.round(km2)} km²`;
  if (km2 >= 1) return `${km2.toFixed(1)} km²`;
  return `${km2.toFixed(2)} km²`;
}

/** "View: 4.2 km², mostly east · water view". */
export function viewText(view: NonNullable<TerrainPayload["view"]>): string | null {
  const parts: string[] = [];
  if (view.area_km2 !== null) {
    let main = area(view.area_km2);
    if (view.direction === "all around") main += ", all around";
    else if (view.direction) main += `, mostly ${view.direction}`;
    parts.push(main);
  }
  if (view.water) parts.push("water view");
  return parts.length ? parts.join(" · ") : null;
}

/** TM05-162: the sun-hours line's estimate label, when an older payload has none. */
export const SUN_HOURS_ESTIMATE = "Bare-earth estimate: shade from trees isn't counted";

/**
 * TM05-162: "About 10 h of direct sun · morning sun", or just "No morning sun" when the
 * hours are unknown. Null when both are.
 */
export function sunHoursText(sun: SunHours): string | null {
  const parts: string[] = [];
  if (sun.hours !== null) parts.push(`About ${Math.round(sun.hours)} h of direct sun`);
  if (sun.morning_sun !== null) {
    const morning = sun.morning_sun ? "morning sun" : "no morning sun";
    parts.push(parts.length ? morning : morning[0].toUpperCase() + morning.slice(1));
  }
  return parts.length ? parts.join(" · ") : null;
}

/** "Faces east: morning sun", or "Flat: sun all day where trees allow". */
export function sunText(sun: NonNullable<TerrainPayload["sun"]>): string {
  if (sun.facing === "flat") return `Flat: ${sun.label}`;
  return `Faces ${sun.facing}: ${sun.label}`;
}

/** The section's lines, in display order, leaving out whatever is unknown. */
export function terrainLines(terrain: TerrainPayload | null | undefined): TerrainLine[] {
  if (!terrain) return [];
  const lines: TerrainLine[] = [];
  if (terrain.pooling) {
    lines.push({
      key: "pooling",
      label: "Water pooling risk",
      value: terrain.pooling.level,
      detail: terrain.pooling.reason || null,
      tone: terrain.pooling.level,
    });
  }
  if (terrain.sun) {
    lines.push({ key: "sun", label: "Sun", value: sunText(terrain.sun), detail: null, tone: null });
  }
  if (terrain.shelter) {
    lines.push({
      key: "shelter",
      label: "Wind",
      value: SHELTER_WORDS[terrain.shelter.level],
      detail: terrain.shelter.reason || null,
      tone: terrain.shelter.level,
    });
  }
  if (terrain.cold_air) {
    lines.push({
      key: "cold_air",
      label: "Cold-air pooling",
      value: terrain.cold_air.level,
      detail: terrain.cold_air.reason || null,
      tone: terrain.cold_air.level,
      estimate: COLD_AIR_ESTIMATE,
    });
  }
  if (terrain.wind) {
    lines.push({
      key: "wind",
      label: "Prevailing wind",
      value: WIND_WORDS[terrain.wind.level],
      detail: terrain.wind.reason || null,
      tone: terrain.wind.level,
      estimate: windEstimate(terrain.wind),
    });
  }
  const sunHours = terrain.sun_hours ? sunHoursText(terrain.sun_hours) : null;
  if (terrain.sun_hours && sunHours) {
    const { reason, morning_reason, estimate } = terrain.sun_hours;
    const detail = [reason, morning_reason].filter(Boolean).join(" ");
    lines.push({
      key: "sun_hours",
      label: "Sun hours",
      value: sunHours,
      detail: detail || null,
      tone: null,
      estimate: estimate || SUN_HOURS_ESTIMATE,
    });
  }
  const view = terrain.view ? viewText(terrain.view) : null;
  if (view) lines.push({ key: "view", label: "View", value: view, detail: null, tone: null });
  return lines;
}

export interface Badge {
  key: "water_view" | "sheltered" | "pooling" | "exposed";
  text: string;
  /** For styling: "good" or "warn". */
  tone: "good" | "warn";
}

/** Compact badges for a list row: only facts worth a glance. */
export function terrainBadges(badges: TerrainBadges | null | undefined): Badge[] {
  if (!badges) return [];
  const out: Badge[] = [];
  if (badges.water_view) out.push({ key: "water_view", text: "Water view", tone: "good" });
  if (badges.shelter === "sheltered") out.push({ key: "sheltered", text: "Sheltered", tone: "good" });
  if (badges.pooling === "high") out.push({ key: "pooling", text: "Pooling risk", tone: "warn" });
  if (badges.shelter === "exposed") out.push({ key: "exposed", text: "Exposed", tone: "warn" });
  return out;
}

/** Find campsites' quick filters (TM05-143). */
export type QuickFilter = "water_view" | "sheltered" | "low_pooling";

export const QUICK_FILTERS: readonly { key: QuickFilter; label: string }[] = [
  { key: "water_view", label: "Water view" },
  { key: "sheltered", label: "Sheltered" },
  { key: "low_pooling", label: "Low pooling risk" },
];

/**
 * Whether a row's terrain passes every active quick filter. A fact that is unknown
 * fails: a filter shows what is known to qualify, never a guess. That includes a
 * potential spot's water view, and whether its pooling risk is low rather than medium.
 */
export function passesQuickFilters(
  badges: TerrainBadges | null | undefined,
  active: ReadonlySet<QuickFilter>,
): boolean {
  if (active.size === 0) return true;
  if (!badges) return false;
  if (active.has("water_view") && badges.water_view !== true) return false;
  if (active.has("sheltered") && badges.shelter !== "sheltered") return false;
  if (active.has("low_pooling") && badges.pooling !== "low") return false;
  return true;
}
