import { test } from "node:test";
import assert from "node:assert/strict";
import {
  area,
  COLD_AIR_ESTIMATE,
  passesQuickFilters,
  TERRAIN_NOTE,
  terrainBadges,
  terrainLines,
  windEstimate,
  type TerrainPayload,
} from "../src/terrain/terrain.ts";
import { measurementText, parseScore } from "../src/score/breakdown.ts";

const FULL: TerrainPayload = {
  pooling: { level: "low", reason: "Water drains away from here (wetness index 6.3)." },
  sun: { facing: "east", label: "morning sun" },
  shelter: { level: "sheltered", reason: "Lies lower than the ground around it, out of the wind." },
  cold_air: { level: "high", reason: "In the lowest ground around." },
  wind: {
    level: "exposed",
    reason: "Open to a west wind: about 2.5 km of open ground upwind.",
    from_deg: 270,
    from: "west",
  },
  view: { area_km2: 4.2, direction: "east", water: true },
  has_viewshed: true,
  note: TERRAIN_NOTE,
};

test("a site with every fact gets six lines in order, worded as the panel shows them", () => {
  const lines = terrainLines(FULL);
  assert.deepEqual(
    lines.map((l) => [l.label, l.value]),
    [
      ["Water pooling risk", "low"],
      ["Sun", "Faces east: morning sun"],
      ["Wind", "Sheltered"],
      ["Cold-air pooling", "high"],
      ["Prevailing wind", "Exposed"],
      ["View", "4.2 km², mostly east · water view"],
    ],
  );
  assert.equal(lines[0].detail, "Water drains away from here (wetness index 6.3).");
  assert.equal(lines[0].tone, "low");
});

test("partial facts: each unknown fact is left out, never shown as zero or 'unknown'", () => {
  const lines = terrainLines({
    ...FULL,
    sun: null,
    shelter: null,
    cold_air: null,
    wind: null,
    view: { area_km2: null, direction: null, water: null },
  });
  assert.deepEqual(
    lines.map((l) => l.key),
    ["pooling"],
  );
  const noWater = terrainLines({ ...FULL, view: { area_km2: 0.35, direction: "all around", water: false } });
  assert.equal(noWater.at(-1)!.value, "0.35 km², all around");
});

test("cold-air pooling is labelled as a terrain estimate, with its reason (TM05-147)", () => {
  const line = terrainLines(FULL).find((l) => l.key === "cold_air")!;
  assert.equal(line.tone, "high");
  assert.equal(line.detail, "In the lowest ground around.");
  assert.equal(line.estimate, COLD_AIR_ESTIMATE);
  assert.match(line.estimate!, /^Terrain estimate/);
  const older: TerrainPayload = { ...FULL, cold_air: undefined };
  assert.ok(!terrainLines(older).some((l) => l.key === "cold_air"), "an older payload has no line");
});

test("prevailing wind shows the direction it assumes, labelled as an estimate (TM05-148)", () => {
  const line = terrainLines(FULL).find((l) => l.key === "wind")!;
  assert.equal(line.tone, "exposed");
  assert.equal(line.detail, "Open to a west wind: about 2.5 km of open ground upwind.");
  assert.equal(line.estimate, "Estimate, assuming the prevailing wind is from the west (270°)");
  const sheltered = terrainLines({ ...FULL, wind: { ...FULL.wind!, level: "sheltered" } });
  assert.equal(sheltered.find((l) => l.key === "wind")!.value, "Wind-sheltered");
  assert.equal(
    windEstimate({ level: "moderate", reason: "", from_deg: 292.5, from: "northwest" }),
    "Estimate, assuming the prevailing wind is from the northwest (293°)",
  );
  assert.ok(!terrainLines({ ...FULL, wind: undefined }).some((l) => l.key === "wind"));
});

test("missing facts: no terrain block means no section", () => {
  assert.deepEqual(terrainLines(null), []);
  assert.deepEqual(terrainLines(undefined), []);
});

test("flat ground faces nowhere", () => {
  const [, sun] = terrainLines({ ...FULL, sun: { facing: "flat", label: "sun all day where trees allow" } });
  assert.equal(sun.value, "Flat: sun all day where trees allow");
});

test("areas are rounded for reading", () => {
  assert.equal(area(12.4), "12 km²");
  assert.equal(area(4.24), "4.2 km²");
  assert.equal(area(0.351), "0.35 km²");
});

test("badges show only what is worth a glance on a list row", () => {
  assert.deepEqual(
    terrainBadges({ pooling: "high", shelter: "sheltered", water_view: true }).map((b) => [b.text, b.tone]),
    [
      ["Water view", "good"],
      ["Sheltered", "good"],
      ["Pooling risk", "warn"],
    ],
  );
  assert.deepEqual(terrainBadges({ pooling: "low", shelter: "moderate", water_view: false }), []);
  assert.deepEqual(terrainBadges(null), []);
});

test("the honest label says what the model can't see", () => {
  assert.match(TERRAIN_NOTE, /bare-earth/);
  assert.match(TERRAIN_NOTE, /Trees, buildings and recent changes aren't counted/);
});

test("quick filters keep only rows known to qualify; unknown facts never pass", () => {
  const lake = { pooling: "low", shelter: "sheltered", water_view: true } as const;
  const ridge = { pooling: "medium", shelter: "exposed", water_view: false } as const;
  const spot = { pooling: null, shelter: null, water_view: null }; // a potential spot
  const on = (...keys: ("water_view" | "sheltered" | "low_pooling")[]) => new Set(keys);
  assert.equal(passesQuickFilters(lake, on()), true);
  assert.equal(passesQuickFilters(null, on()), true); // no filter: everything shows
  assert.equal(passesQuickFilters(lake, on("water_view", "sheltered", "low_pooling")), true);
  assert.equal(passesQuickFilters(ridge, on("water_view")), false);
  assert.equal(passesQuickFilters(ridge, on("low_pooling")), false);
  assert.equal(passesQuickFilters(spot, on("water_view")), false);
  assert.equal(passesQuickFilters(spot, on("low_pooling")), false);
  assert.equal(passesQuickFilters(null, on("sheltered")), false);
});

test("an exposed site or spot gets an Exposed badge", () => {
  assert.deepEqual(
    terrainBadges({ pooling: null, shelter: "exposed", water_view: null }).map((b) => [b.text, b.tone]),
    [["Exposed", "warn"]],
  );
});

test("the score breakdown shows a terrain factor in the engine's own words", () => {
  const score = parseScore({
    contract: 1,
    score: 81,
    caps: [],
    factors: [
      {
        key: "drainage",
        label: "Drainage",
        status: "scored",
        score: 100,
        contribution: 9.1,
        measurement: { pooling: "low", twi: 7.2 },
        explanation: "Water pooling risk low. Water drains away from here (wetness index 7.2).",
      },
    ],
  });
  assert.ok(score);
  assert.equal(score.factors[0].label, "Drainage");
  assert.match(measurementText(score.factors[0]), /^Water pooling risk low/);
});
