/**
 * TM05-82: how the trail panel words a route type, and labels a guess as a guess.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { routeTypeText } from "../src/trails/format.ts";

test("a measured loop is stated plainly", () => {
  const text = routeTypeText({ label: "Loop", estimated: false, basis: { ends_apart_m: 42.4 } });
  assert.equal(text.value, "Loop");
  assert.match(text.hint, /42 m apart/);
});

test("an estimate says so, and says what it rests on", () => {
  const text = routeTypeText({
    label: "Out & back",
    estimated: true,
    basis: { ends_apart_m: 8415.6, start: "dead_end", end: "summit" },
  });
  assert.equal(text.value, "Out & back (est.)");
  assert.match(text.hint, /a dead end/);
  assert.match(text.hint, /a summit/);
});
