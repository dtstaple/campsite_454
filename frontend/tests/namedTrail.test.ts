/**
 * TM05-97: which trail segments open the trail panel and which keep the popup.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { isNamedTrail } from "../src/trails/format.ts";

test("a named segment opens the trail panel", () => {
  assert.equal(isNamedTrail({ name: "Adirondack Rail Trail", trail_type: "path" }), true);
});

test("an unnamed or blank-named segment keeps the popup", () => {
  assert.equal(isNamedTrail({ name: "" }), false);
  assert.equal(isNamedTrail({ name: "   " }), false);
  assert.equal(isNamedTrail({ name: null }), false);
  assert.equal(isNamedTrail({}), false);
  assert.equal(isNamedTrail(null), false);
});
