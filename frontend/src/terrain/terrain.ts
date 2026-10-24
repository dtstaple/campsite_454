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

export interface TerrainPayload {
  pooling: { level: PoolingLevel; reason: string } | null;
  sun: { facing: string; label: string } | null;
  shelter: { level: ShelterLevel; reason: string } | null;
  view: { area_km2: number | null; direction: string | null; water: boolean | null } | null;
  has_viewshed: boolean;
  note: string;
}

/** The compact form on list rows: only what a badge needs. */
export interface TerrainBadges {
  pooling: PoolingLevel | null;
  shelter: ShelterLevel | null;
  water_view: boolean | null;
}

export interface TerrainLine {
  key: "pooling" | "sun" | "shelter" | "view";
  label: string;
  value: string;
  detail: string | null;
  /** For styling: a pooling or shelter level. */
  tone: string | null;
}

/** Shown under the section whenever it is. */
export const TERRAIN_NOTE =
  "Terrain-model estimate from bare-earth elevation. Trees, buildings and recent changes aren't counted.";

const SHELTER_WORDS: Record<ShelterLevel, string> = {
  sheltered: "Sheltered",
  moderate: "Moderate shelter",
  exposed: "Exposed",
};

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
