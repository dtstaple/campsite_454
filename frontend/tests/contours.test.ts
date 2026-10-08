import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CONTOUR_MIN_ZOOM,
  CONTOUR_THRESHOLDS_FT,
  INDEX_EVERY,
  contourLabel,
  intervalsAt,
  isIndex,
} from "../src/map/contourConfig.ts";

test("every zoom's index line is the fifth line", () => {
  for (const [minor, index] of Object.values(CONTOUR_THRESHOLDS_FT)) {
    assert.equal(index, minor * INDEX_EVERY);
  }
});

test("contours start at zoom 12 and get finer closer in", () => {
  assert.equal(CONTOUR_MIN_ZOOM, 12);
  assert.equal(intervalsAt(11.9), null);
  assert.deepEqual(intervalsAt(12), [40, 200]);
  assert.deepEqual(intervalsAt(13.7), [40, 200]);
  assert.deepEqual(intervalsAt(14), [20, 100]);
  assert.deepEqual(intervalsAt(18), [20, 100]);
});

test("index lines fall on round elevations", () => {
  assert.ok(isIndex(2000, 12));
  assert.ok(!isIndex(2040, 12));
  assert.ok(isIndex(2100, 14));
  assert.ok(!isIndex(2100, 12));
});

test("labels are in feet", () => {
  assert.equal(contourLabel(1240), "1,240 ft");
  assert.equal(contourLabel(5343.6), "5,344 ft");
});
