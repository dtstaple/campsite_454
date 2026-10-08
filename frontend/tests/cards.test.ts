import { test } from "node:test";
import assert from "node:assert/strict";
import { campsitesLine, cardFacts, nearPoint, sparklinePoints } from "../src/trails/cards.ts";

test("a card reads distance, gain, difficulty and type", () => {
  assert.deepEqual(
    cardFacts({ length_m: 11426.3, gain_m: 1007.4, difficulty: "hard", route_type: "out_and_back", route_type_estimated: true }),
    ["7.1 mi", "3,305 ft gain", "Hard", "Out & back (est.)"],
  );
  assert.deepEqual(cardFacts({ length_m: 1609.344, gain_m: null, route_type: "loop", route_type_estimated: false }), [
    "1.0 mi",
    "gain not measured yet",
    "Loop",
  ]);
});

test("campsites are counted honestly", () => {
  assert.equal(campsitesLine({ length_m: 1, gain_m: 0, campsites: 0, campsites_within_m: 500 }), "No mapped campsites within 500 m");
  assert.equal(campsitesLine({ length_m: 1, gain_m: 0, campsites: 1 }), "1 campsite within 500 m");
  assert.equal(campsitesLine({ length_m: 1, gain_m: 0, campsites: 8, campsites_within_m: 1000 }), "8 campsites within 1 km");
});

test("the sparkline puts the low point at the bottom and the high point at the top", () => {
  const points = sparklinePoints([100, 200, 150], 100, 20)!.split(" ").map((p) => p.split(",").map(Number));
  assert.deepEqual(points.map((p) => p[0]), [2, 50, 98]);
  assert.deepEqual(points.map((p) => p[1]), [18, 2, 10]);
  assert.equal(sparklinePoints([5], 100, 20), null);
  assert.equal(sparklinePoints(null, 100, 20), null);
  assert.ok(sparklinePoints([7, 7, 7], 100, 20)!.split(" ").every((p) => p.endsWith(",10.0")));
});

test("distance is measured from the last map view when it is in the region", () => {
  const box: [number, number, number, number] = [-75, 43, -73, 45];
  assert.deepEqual(nearPoint([-74, 44], box), [-74, 44]);
  assert.deepEqual(nearPoint([-71, 44], box), [-74, 44]);
  assert.deepEqual(nearPoint(null, box), [-74, 44]);
});
