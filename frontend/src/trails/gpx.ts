/**
 * Where a trail's GPX download lives (TM05-79). Pure, so node --test can load it.
 *
 * A route relation has its own endpoint; a trail assembled from same-name segments
 * (TM05-97) has no relation, so it is exported through the way it was opened from.
 */

export interface GpxTarget {
  osm_id: number | null;
  assembly?: { from_way: string } | null;
}

/** The API path (no host) of the trail's GPX, with its campsite distance. */
export function gpxPath(detail: GpxTarget, withinM: number): string | null {
  const query = `?campsites_within_m=${withinM}`;
  if (detail.osm_id !== null) return `/api/routes/${detail.osm_id}/gpx/${query}`;
  const way = detail.assembly?.from_way;
  if (!way) return null;
  const path = way.split("/").map(encodeURIComponent).join("/");
  return `/api/trails/${path}/gpx/${query}`;
}

/** The same file name the API gives the download (api/gpx.py `filename`). */
export function gpxFilename(name: string): string {
  const slug = (name || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `${slug || "trail"}.gpx`;
}
