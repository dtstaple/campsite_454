/**
 * TM05-71: the trail list's campsite name, derived where the source has none.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { campsiteName } from "../src/trails/format.ts";

test("a real name is shown as is", () => {
  assert.deepEqual(campsiteName({ name: "Marcy Dam", display_name: "Marcy Dam", display_name_derived: false }), {
    text: "Marcy Dam",
    derived: false,
  });
});

test("a derived name is shown and flagged", () => {
  assert.deepEqual(
    campsiteName({ name: null, display_name: "Campsite near Calamity Brook", display_name_derived: true }),
    { text: "Campsite near Calamity Brook", derived: true },
  );
});

test("no display name falls back to the source name, then 'Unnamed campsite'", () => {
  assert.deepEqual(campsiteName({ name: "Lean-to #2" }), { text: "Lean-to #2", derived: false });
  assert.deepEqual(campsiteName({ name: null, display_name: null }), { text: "Unnamed campsite", derived: false });
});
