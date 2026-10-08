import { test } from "node:test";
import assert from "node:assert/strict";
import { nearestSnap, nextSnap, snapHeights } from "../src/components/snaps.ts";
import { accuracyCircle, alongTrail, mileLabel } from "../src/location/live.ts";
import { haversineM, measure } from "../src/trails/geometry.ts";

test("sheet heights for an iPhone-sized map", () => {
  // 844 px screen, less the slim header and the status bar: about 760 px of map.
  assert.deepEqual(snapHeights(760), { peek: 132, half: 380, full: 704 });
  // A tiny window never makes peek taller than full.
  const tiny = snapHeights(150);
  assert.ok(tiny.peek <= tiny.full && tiny.half >= tiny.peek);
});

test("a drag settles on the nearest height; a flick moves one step", () => {
  const heights = snapHeights(760);
  assert.equal(nearestSnap(200, heights), "peek");
  assert.equal(nearestSnap(420, heights), "half");
  assert.equal(nearestSnap(650, heights), "full");
  assert.equal(nearestSnap(300, heights, -1.2, "half"), "full"); // fast upward
  assert.equal(nearestSnap(300, heights, 1.2, "half"), "peek"); // fast downward
  assert.equal(nearestSnap(300, heights, 1.2, "peek"), "peek");
});

test("tapping the handle cycles the sizes", () => {
  assert.equal(nextSnap("peek"), "half");
  assert.equal(nextSnap("half"), "full");
  assert.equal(nextSnap("full"), "peek");
});

test("the accuracy circle is that many metres from the point all round", () => {
  const centre: [number, number] = [-73.95, 44.16];
  const ring = accuracyCircle(centre, 35);
  assert.equal(ring.length, 49);
  assert.deepEqual(ring[0], ring[48]);
  for (const point of ring) assert.ok(Math.abs(haversineM(centre, point) - 35) < 0.2);
});

test("the mile along the open trail, only while on it", () => {
  // A trail due east along 44 N, about 1.6 km long.
  const line = measure([
    [-74.0, 44.0],
    [-73.98, 44.0],
  ]);
  const onIt: [number, number] = [-73.99, 44.0001]; // ~11 m off, halfway
  const { alongM, offM } = alongTrail(line, onIt);
  assert.ok(Math.abs(alongM - line.length / 2) < 5 && offM < 15);
  assert.equal(mileLabel(line, onIt, "Test Trail"), "mi 0.5 along Test Trail");
  assert.equal(mileLabel(line, [-73.99, 44.01], "Test Trail"), null); // ~1.1 km off
});
