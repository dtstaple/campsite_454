/**
 * TM05-73: the trail list gives a mile only to sites that are along the route.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { campsitePlace, isAlong } from "../src/trails/format.ts";

test("a site along the route keeps its mile marker", () => {
  const place = campsitePlace({ distance_along_m: 3540, distance_from_route_m: 84.3, position: "along" });
  assert.deepEqual(place, { mile: "mi 2.2", off: "84 m off trail" });
});

test("a site past the trailhead gets no mile", () => {
  const site = {
    distance_along_m: 0,
    distance_from_route_m: 763.3,
    position: "near_start",
    position_label: "near the trailhead",
  };
  assert.deepEqual(campsitePlace(site), { mile: "—", off: "near the trailhead · 763 m away" });
  assert.equal(isAlong(site), false);
});

test("an older API without positions still shows miles", () => {
  assert.equal(isAlong({}), true);
  assert.equal(campsitePlace({ distance_along_m: 0, distance_from_route_m: 10 }).mile, "mi 0.0");
});
