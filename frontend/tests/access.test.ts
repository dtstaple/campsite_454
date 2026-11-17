import { test } from "node:test";
import assert from "node:assert/strict";
import { accessText, passesAccessFilter, type Access } from "../src/campsite/access.ts";

const EASY: Access = {
  class: "easy",
  label: "Easy access",
  reason: "0.5 km and 0 m of climb from West Lot, about 6 min by Naismith's rule: within 3 km.",
  trailhead: "West Lot",
  distance_m: 520,
  gain_m: 0,
  time_s: 374,
};
const HARD: Access = { ...EASY, class: "hard", label: "Hard access" };
const UNKNOWN: Access = {
  class: "unknown",
  label: "Access unknown",
  reason: "No trailhead connects to the trails near this site, so its access is not known.",
  trailhead: null,
  distance_m: null,
  gain_m: null,
  time_s: null,
};

test("the Easy access filter keeps only easy sites", () => {
  assert.equal(passesAccessFilter(EASY, true), true);
  assert.equal(passesAccessFilter(HARD, true), false);
});

test("unknown or uncomputed access never passes the filter", () => {
  assert.equal(passesAccessFilter(UNKNOWN, true), false);
  assert.equal(passesAccessFilter(null, true), false);
  assert.equal(passesAccessFilter(undefined, true), false);
});

test("with the filter off, every site shows", () => {
  for (const access of [EASY, HARD, UNKNOWN, null, undefined]) {
    assert.equal(passesAccessFilter(access, false), true);
  }
});

test("the panel shows the label and the one-line reason", () => {
  assert.deepEqual(accessText(EASY), { label: "Easy access", reason: EASY.reason });
  assert.deepEqual(accessText(UNKNOWN), { label: "Access unknown", reason: UNKNOWN.reason });
  assert.equal(accessText(null), null);
});
