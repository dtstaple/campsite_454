import { test } from "node:test";
import assert from "node:assert/strict";
import { shareUrl, stripMarks } from "../src/plans/share.ts";

test("a share link is the site's origin, /shared/, and the token", () => {
  assert.equal(shareUrl("https://campsite.example", "abc_123-XYZ"), "https://campsite.example/shared/abc_123-XYZ");
  assert.equal(shareUrl("http://localhost:5173/", "t"), "http://localhost:5173/shared/t");
});

test("stops are placed along the route strip by distance", () => {
  const marks = stripMarks(4000, [
    { night: 1, display_name: "Lower Camp", distance_along_m: 1000 },
    { night: 2, display_name: null, distance_along_m: 3000 },
  ]);
  assert.deepEqual(marks, [
    { night: 1, label: "Lower Camp", percent: 25 },
    { night: 2, label: "Campsite", percent: 75 },
  ]);
});

test("a stop is kept on the strip even past the route's ends", () => {
  const marks = stripMarks(1000, [
    { night: 1, display_name: "Before", distance_along_m: -5 },
    { night: 2, display_name: "After", distance_along_m: 1200 },
  ]);
  assert.deepEqual(
    marks.map((m) => m.percent),
    [0, 100],
  );
  assert.equal(stripMarks(0, [{ night: 1, display_name: "x", distance_along_m: 5 }])[0].percent, 0);
});
