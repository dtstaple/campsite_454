/**
 * TM05-85: the Discover filters' conversion to API parameters (miles and feet to metres).
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { NO_FILTERS, activeFilterCount, filterParams, toggled, unknownNote } from "../src/trails/filters.ts";

test("no filters, no parameters", () => {
  assert.deepEqual(filterParams(NO_FILTERS), {});
  assert.equal(activeFilterCount(NO_FILTERS), 0);
});

test("miles and feet become metres; empty and invalid fields are left out", () => {
  const params = filterParams({
    ...NO_FILTERS,
    minLengthMi: "2",
    maxLengthMi: "abc",
    minGainFt: "1000",
    maxGainFt: "-5",
  });
  assert.deepEqual(params, { min_length_m: "3219", min_gain_m: "305" });
});

test("choices are joined, and filters combine", () => {
  const params = filterParams({
    ...NO_FILTERS,
    difficulty: ["hard", "easy"],
    routeType: ["loop"],
    campsitesWithinM: 500,
  });
  assert.deepEqual(params, { difficulty: "easy,hard", route_type: "loop", campsites_within_m: "500" });
  assert.equal(activeFilterCount({ ...NO_FILTERS, difficulty: ["easy"], campsitesWithinM: 500 }), 2);
});

test("toggling a choice adds or removes it", () => {
  assert.deepEqual(toggled(["easy"], "hard"), ["easy", "hard"]);
  assert.deepEqual(toggled(["easy", "hard"], "easy"), ["hard"]);
});

test("routes the filters cannot judge are mentioned", () => {
  assert.equal(unknownNote(0), null);
  assert.equal(unknownNote(1), "1 trail has no elevation data yet, so these filters can't include them.");
});
