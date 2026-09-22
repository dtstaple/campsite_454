/**
 * Bridge between the CSS custom properties in theme.css and the places that need a
 * real value in JavaScript -- chiefly MapLibre paint properties, which cannot take a
 * `var(--x)`.
 *
 * Reading them back out of the stylesheet keeps theme.css the single source of truth.
 * Change a colour there and both the chrome and the map follow.
 */

/** One custom property's computed value, trimmed. */
export function token(name: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name);
  return value.trim();
}

/**
 * Map layer colours, read once when the map is built.
 *
 * Falls back to the literal v1 values if the stylesheet has not applied yet, so a
 * timing quirk degrades to the right colours rather than to empty strings, which
 * MapLibre would reject.
 */
export function mapColors() {
  return {
    water: token("--map-water") || "#4fc3f7",
    trails: token("--map-trails") || "#f4a261",
    campsites: token("--map-campsites") || "#ff5a68",
    /* Stays light on purpose. Against a #333 basemap an off-white ring reads at
     * 10.25:1 and lifts the marker clear of the terrain; a dark ring manages only
     * 1.47:1 and the marker's edge dissolves into the basemap. */
    campsiteStroke: token("--text-primary") || "#ede7d9",
  };
}

/** A numeric token -- opacity or width -- with a fallback if it is unset. */
export function numericToken(name: string, fallback: number): number {
  const parsed = Number.parseFloat(token(name));
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** Every map paint value that is tunable from theme.css. */
export function mapPaint() {
  return {
    waterLineOpacity: numericToken("--map-water-line-opacity", 0.95),
    waterLineWidth: numericToken("--map-water-line-width", 1.2),
    waterFillOpacity: numericToken("--map-water-fill-opacity", 0.55),
    trailsOpacity: numericToken("--map-trails-opacity", 0.95),
    trailsWidth: numericToken("--map-trails-width", 1.6),
    campsitesOpacity: numericToken("--map-campsites-opacity", 1),
    campsitesRadius: numericToken("--map-campsites-radius", 6),
    campsitesStrokeWidth: numericToken("--map-campsites-stroke-width", 1.5),
    hitWidth: numericToken("--map-hit-width", 14),
  };
}
