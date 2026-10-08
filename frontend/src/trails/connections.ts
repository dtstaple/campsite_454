/**
 * Connecting trails (TM05-101): the named trails this one meets at a junction node.
 * Pure, so node --test checks the ordering and the wording.
 */

export interface Junction {
  node_id: number;
  lon: number;
  lat: number;
  distance_along_m: number;
}

export interface Connection {
  name: string;
  /** The route to open, or null for an assembled trail opened through `way_id`. */
  osm_id: number | null;
  way_id: string | null;
  junctions: Junction[];
}

const M_PER_MI = 1609.344;

/** "mi 1.0" or "mi 1.0 and 2.3": where along this trail it meets the other one. */
export function junctionMiles(connection: Connection): string {
  const miles = connection.junctions.map((j) => (j.distance_along_m / M_PER_MI).toFixed(1));
  if (miles.length === 0) return "";
  if (miles.length === 1) return `mi ${miles[0]}`;
  return `mi ${miles.slice(0, -1).join(", ")} and ${miles[miles.length - 1]}`;
}

/** In order of the first junction along this trail, then by name. */
export function byMile(connections: readonly Connection[]): Connection[] {
  return [...connections].sort(
    (a, b) =>
      (a.junctions[0]?.distance_along_m ?? Infinity) - (b.junctions[0]?.distance_along_m ?? Infinity) ||
      a.name.localeCompare(b.name),
  );
}

/** What to open for a connection: TrailInsight's own selection shape. */
export function connectionTarget(
  connection: Connection,
): { osmId: number; name: string } | { wayId: string; name: string } | null {
  if (connection.osm_id !== null) return { osmId: connection.osm_id, name: connection.name };
  if (connection.way_id) return { wayId: connection.way_id, name: connection.name };
  return null;
}
