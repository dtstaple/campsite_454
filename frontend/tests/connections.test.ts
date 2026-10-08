import { test } from "node:test";
import assert from "node:assert/strict";
import { byMile, connectionTarget, junctionMiles, type Connection } from "../src/trails/connections.ts";

const at = (m: number) => ({ node_id: m, lon: 0, lat: 0, distance_along_m: m });
const c = (name: string, metres: number[], osm_id: number | null = null): Connection => ({
  name,
  osm_id,
  way_id: osm_id === null ? `way/${name.length}` : null,
  junctions: metres.map(at),
});

test("connections are ordered by their first junction's mile", () => {
  const ordered = byMile([c("Upper", [4000]), c("Lower", [500]), c("Middle", [1609.344, 6000])]);
  assert.deepEqual(ordered.map((e) => e.name), ["Lower", "Middle", "Upper"]);
});

test("miles read naturally", () => {
  assert.equal(junctionMiles(c("A", [1609.344])), "mi 1.0");
  assert.equal(junctionMiles(c("A", [1609.344, 3701.5])), "mi 1.0 and 2.3");
  assert.equal(junctionMiles(c("A", [0, 1609.344, 3701.5])), "mi 0.0, 1.0 and 2.3");
});

test("a route opens by relation, an assembled trail by its way", () => {
  assert.deepEqual(connectionTarget(c("Summit", [1], 7)), { osmId: 7, name: "Summit" });
  assert.deepEqual(connectionTarget(c("Spur", [1])), { wayId: "way/4", name: "Spur" });
});
