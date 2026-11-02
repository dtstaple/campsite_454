/**
 * Terrain along a route (TM05-152): the route detail's `terrain_along` block as the trail
 * panel shows it. Shaded stretches on the elevation profile, a legend, and summary lines
 * such as "1.2 mi exposed ridge". Pure, so node --test can load it.
 */

export type AlongLayer = "exposure" | "pooling-risk";

export interface AlongStretch {
  layer: AlongLayer;
  zone_class: string;
  label: string;
  start_m: number;
  end_m: number;
  length_m: number;
}

export interface AlongTotal {
  layer: AlongLayer;
  zone_class: string;
  label: string;
  legend: string;
  length_m: number;
  stretches: number;
  share_pct: number;
}

export interface TerrainAlong {
  status: "ok" | "unavailable";
  reason: string | null;
  stretches: AlongStretch[];
  totals: AlongTotal[];
  note: string;
}

export interface ChartBand {
  start: number;
  end: number;
  layer: AlongLayer;
  label: string;
}

/** The stretches to shade, clipped to the profile's length. */
export function chartBands(along: TerrainAlong | null | undefined, lengthM: number): ChartBand[] {
  if (!along || along.status !== "ok") return [];
  return along.stretches
    .map((s) => ({
      start: Math.max(0, s.start_m),
      end: Math.min(lengthM, s.end_m),
      layer: s.layer,
      label: s.label,
    }))
    .filter((band) => band.end > band.start);
}

/** Legend entries: only the kinds the route actually crosses. */
export function legendItems(along: TerrainAlong | null | undefined): AlongTotal[] {
  if (!along || along.status !== "ok") return [];
  return along.totals.filter((t) => t.length_m > 0);
}

/**
 * The panel's summary lines, longest first: "1.2 mi exposed ridge (3 stretches)". A
 * route that crosses neither says so in one line, and an unavailable block gives its
 * reason, so the section never just disappears.
 */
export function summaryLines(
  along: TerrainAlong | null | undefined,
  formatDistance: (metres: number) => string,
): string[] {
  if (!along) return [];
  if (along.status !== "ok") return [along.reason ?? "Terrain along this route is unavailable."];
  const crossed = legendItems(along).sort((a, b) => b.length_m - a.length_m);
  if (crossed.length === 0) {
    const kinds = along.totals.map((t) => t.label).join(" or ");
    return [`No ${kinds || "exposed or wet ground"} mapped along this route.`];
  }
  return crossed.map((t) => {
    const count = t.stretches === 1 ? "1 stretch" : `${t.stretches} stretches`;
    return `${formatDistance(t.length_m)} ${t.label} (${count})`;
  });
}
