/**
 * Peak and trailhead labels (TM05-122). Pure, so node --test can load it; layers.ts draws
 * them.
 *
 * The API serves both as opt-in GeoJSON points from TM05-89 (docs/api.md, `layers=`). A
 * peak carries `name` and `elevation_m`, which is null when OpenStreetMap has no usable
 * `ele`; a trailhead carries `name`. Either name may be empty.
 *
 * Elevation is shown in feet, like the contours and US trail signage. A missing elevation
 * is left off rather than guessed: the label is then the name alone.
 */

import type { FeatureCollection } from "geojson";
import { FT_PER_M } from "./contourConfig.ts";

/** The property the symbol layers read their text from. */
export const LABEL_PROPERTY = "label";

/**
 * Peaks appear from this zoom. Below it the Adirondacks' few hundred summits pile into
 * each other and hide the place names.
 */
export const PEAK_MIN_ZOOM = 10;

/** Trailheads appear from this zoom, where the trails they start are drawn too. */
export const TRAILHEAD_MIN_ZOOM = 12;

/** Metres to whole feet. */
export function metresToFeet(metres: number): number {
  return Math.round(metres * FT_PER_M);
}

/** A usable elevation in metres, or null for missing or non-numeric values. */
function elevationOf(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** "4,322 ft", or null when there is no elevation. */
export function elevationLabel(elevationM: unknown): string | null {
  const metres = elevationOf(elevationM);
  return metres === null ? null : `${metresToFeet(metres).toLocaleString("en-US")} ft`;
}

/** The popup's elevation row: "5,344 ft (1,629 m)", or null when there is none. */
export function elevationDetail(elevationM: unknown): string | null {
  const metres = elevationOf(elevationM);
  if (metres === null) return null;
  return `${elevationLabel(metres)} (${Math.round(metres).toLocaleString("en-US")} m)`;
}

/**
 * A peak's map label: "Mount Marcy · 5,344 ft". With no elevation, just the name; with
 * no name, just the elevation; with neither, empty, so nothing is drawn.
 */
export function peakLabel(name: unknown, elevationM: unknown): string {
  const title = typeof name === "string" ? name.trim() : "";
  const elevation = elevationLabel(elevationM);
  return [title, elevation].filter(Boolean).join(" · ");
}

/** A trailhead's map label: its name, or empty so only the icon is drawn. */
export function trailheadLabel(name: unknown): string {
  return typeof name === "string" ? name.trim() : "";
}

/** The collection with each feature's label stored as `properties.label`, for setData(). */
export function withLabels<T extends FeatureCollection>(
  collection: T,
  layer: "peaks" | "trailheads",
): T {
  return {
    ...collection,
    features: collection.features.map((feature) => {
      const properties = feature.properties ?? {};
      const label =
        layer === "peaks"
          ? peakLabel(properties.name, properties.elevation_m)
          : trailheadLabel(properties.name);
      return { ...feature, properties: { ...properties, [LABEL_PROPERTY]: label } };
    }),
  };
}
