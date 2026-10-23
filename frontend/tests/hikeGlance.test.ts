import { test } from "node:test";
import assert from "node:assert/strict";
import { glanceItems } from "../src/tracking/glance.ts";
import { mileOf } from "../src/tracking/progress.ts";

const MI = 1609.344;
const units = (text: string) => (text.match(/\bmi\b/g) ?? []).length;

test("on a 137 mi trail each glance value carries its unit once", () => {
  // The TM05-138 report: "1.51 mi mi 1.5 of 137." on the Northville-Placid Trail.
  const items = glanceItems(
    { elapsedMs: (1 * 3600 + 7 * 60 + 3) * 1000, distanceM: 1.51 * MI, paceMinPerMi: 22.5 },
    { doneM: 1.5 * MI, totalM: 137.4 * MI },
  );
  assert.deepEqual(items, [
    { label: "Elapsed", value: "1:07:03" },
    { label: "Distance", value: "1.51 mi" },
    { label: "Trail", value: "1.5 of 137 mi" },
  ]);
  for (const item of items.slice(1)) assert.equal(units(item.value), 1, item.value);
  assert.ok(!items.map((i) => i.value).join(" ").includes("mi mi"));
});

test("a long distance and a long trail stay short enough to sit on one line each", () => {
  const items = glanceItems(
    { elapsedMs: 49 * 3600 * 1000, distanceM: 128.73 * MI, paceMinPerMi: 31 },
    { doneM: 128.7 * MI, totalM: 137.4 * MI },
  );
  assert.equal(items[1].value, "128.73 mi");
  assert.equal(items[2].value, "128.7 of 137 mi");
  // The widest values at 390 px: none longer than the panel's glance column allows.
  for (const item of items) assert.ok(item.value.length <= 16, `${item.label}: ${item.value}`);
});

test("free walks show the pace instead of trail progress", () => {
  const items = glanceItems({ elapsedMs: 0, distanceM: 0, paceMinPerMi: null }, null);
  assert.deepEqual(items[2], { label: "Pace", value: "–" });
});

test("a short trail keeps its decimal; a long one drops it", () => {
  assert.equal(mileOf({ doneM: 2.3 * MI, totalM: 7.42 * MI }), "2.3 of 7.4 mi");
  assert.equal(mileOf({ doneM: 99.9 * MI, totalM: 99.94 * MI }), "99.9 of 99.9 mi");
  assert.equal(mileOf({ doneM: 1.5 * MI, totalM: 137.4 * MI }), "1.5 of 137 mi");
});
