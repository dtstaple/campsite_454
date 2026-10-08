/**
 * TM05-74: the trail search list's wording.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { emptySearchMessage, routeHitMeta } from "../src/trails/format.ts";

test("length, gain and distance, gain left out until it is known", () => {
  assert.equal(
    routeHitMeta({ length_m: 7081, gain_m: 1007, distance_m: 5149 }),
    "4.4 mi · 3,304 ft gain · 3.2 mi away",
  );
  assert.equal(routeHitMeta({ length_m: 7081, gain_m: null, distance_m: 40 }), "4.4 mi · in view");
  assert.equal(routeHitMeta({ length_m: 7081, gain_m: null, distance_m: null }), "4.4 mi");
});

test("an empty list says why", () => {
  assert.equal(emptySearchMessage("zzzz"), 'No named trails match "zzzz".');
  assert.match(emptySearchMessage(""), /No named trails in or near this view/);
  assert.equal(emptySearchMessage("", true), "No trails here match these filters. Loosen them, or clear them.");
});
