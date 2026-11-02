import { test } from "node:test";
import assert from "node:assert/strict";
import {
  chartBands,
  legendItems,
  summaryLines,
  type TerrainAlong,
} from "../src/terrain/along.ts";

const miles = (m: number) => `${(m / 1609.344).toFixed(1)} mi`;

function along(overrides: Partial<TerrainAlong> = {}): TerrainAlong {
  return {
    status: "ok",
    reason: null,
    note: "Terrain-model estimate from bare-earth elevation.",
    stretches: [
      { layer: "pooling-risk", zone_class: "high", label: "wet ground", start_m: 300, end_m: 950, length_m: 650 },
      { layer: "exposure", zone_class: "high", label: "exposed ridge", start_m: 4000, end_m: 5000, length_m: 1000 },
      { layer: "exposure", zone_class: "high", label: "exposed ridge", start_m: 7000, end_m: 8100, length_m: 1100 },
    ],
    totals: [
      { layer: "exposure", zone_class: "high", label: "exposed ridge", legend: "", length_m: 2100, stretches: 2, share_pct: 21 },
      { layer: "pooling-risk", zone_class: "high", label: "wet ground", legend: "", length_m: 650, stretches: 1, share_pct: 6.5 },
    ],
    ...overrides,
  };
}

test("summary lines read like the story: distance, kind, stretches, longest first", () => {
  assert.deepEqual(summaryLines(along(), miles), [
    "1.3 mi exposed ridge (2 stretches)",
    "0.4 mi wet ground (1 stretch)",
  ]);
});

test("a route crossing neither says so rather than showing nothing", () => {
  const none = along({
    stretches: [],
    totals: along().totals.map((t) => ({ ...t, length_m: 0, stretches: 0, share_pct: 0 })),
  });
  assert.deepEqual(summaryLines(none, miles), ["No exposed ridge or wet ground mapped along this route."]);
  assert.deepEqual(legendItems(none), []);
  assert.deepEqual(chartBands(none, 10000), []);
});

test("an unavailable block gives its reason and shades nothing", () => {
  const off = along({ status: "unavailable", reason: "Not computed yet.", stretches: [], totals: [] });
  assert.deepEqual(summaryLines(off, miles), ["Not computed yet."]);
  assert.deepEqual(chartBands(off, 10000), []);
  assert.deepEqual(summaryLines(undefined, miles), []);
});

test("bands follow the stretches, clipped to the profile", () => {
  const bands = chartBands(along(), 7500);
  assert.deepEqual(
    bands.map((b) => [b.layer, b.start, b.end]),
    [
      ["pooling-risk", 300, 950],
      ["exposure", 4000, 5000],
      ["exposure", 7000, 7500],
    ],
  );
});
