/**
 * Trail cards on the Discover page (TM05-102): the wording and the sparkline. Pure, so
 * node --test checks it.
 */

const M_PER_MI = 1609.344;
const FT_PER_M = 3.28084;

export const DIFFICULTY_LABELS = { easy: "Easy", moderate: "Moderate", hard: "Hard" } as const;
export const ROUTE_TYPE_LABELS = {
  loop: "Loop",
  out_and_back: "Out & back",
  point_to_point: "Point to point",
} as const;

export interface CardFacts {
  length_m: number;
  gain_m: number | null;
  difficulty?: keyof typeof DIFFICULTY_LABELS | null;
  route_type?: keyof typeof ROUTE_TYPE_LABELS | null;
  route_type_estimated?: boolean | null;
  campsites?: number;
  campsites_within_m?: number;
}

/** The facts line under a card's name: "7.1 mi · 3,305 ft gain · Hard · Out & back (est.)". */
export function cardFacts(hit: CardFacts): string[] {
  const parts = [`${(hit.length_m / M_PER_MI).toFixed(1)} mi`];
  parts.push(hit.gain_m === null ? "gain not measured yet" : `${Math.round(hit.gain_m * FT_PER_M).toLocaleString("en-US")} ft gain`);
  if (hit.difficulty) parts.push(DIFFICULTY_LABELS[hit.difficulty]);
  if (hit.route_type) {
    parts.push(ROUTE_TYPE_LABELS[hit.route_type] + (hit.route_type_estimated && hit.route_type !== "loop" ? " (est.)" : ""));
  }
  return parts;
}

/** "3 campsites within 500 m", "No mapped campsites within 500 m". */
export function campsitesLine(hit: CardFacts): string {
  const within = hit.campsites_within_m ?? 500;
  const where = within < 1000 ? `${within} m` : `${within / 1000} km`;
  const count = hit.campsites ?? 0;
  if (count === 0) return `No mapped campsites within ${where}`;
  return `${count} campsite${count === 1 ? "" : "s"} within ${where}`;
}

/**
 * An SVG polyline `points` attribute for a sparkline in a width x height box, lowest
 * elevation at the bottom. A flat profile draws along the middle. Null with fewer than
 * two values.
 */
export function sparklinePoints(values: readonly number[] | null | undefined, width: number, height: number, pad = 2): string | null {
  if (!values || values.length < 2) return null;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low;
  const step = (width - 2 * pad) / (values.length - 1);
  return values
    .map((value, i) => {
      const x = pad + i * step;
      const y = span === 0 ? height / 2 : pad + (1 - (value - low) / span) * (height - 2 * pad);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

/** Where "distance from view" measures from: the last map view, if it is in the region. */
export function nearPoint(
  lastView: [number, number] | null,
  bbox: [number, number, number, number],
): [number, number] {
  const [west, south, east, north] = bbox;
  if (lastView && lastView[0] >= west && lastView[0] <= east && lastView[1] >= south && lastView[1] <= north) {
    return lastView;
  }
  return [(west + east) / 2, (south + north) / 2];
}
