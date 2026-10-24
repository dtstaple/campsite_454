import { test } from "node:test";
import assert from "node:assert/strict";
import {
  area,
  TERRAIN_NOTE,
  terrainBadges,
  terrainLines,
  type TerrainPayload,
} from "../src/terrain/terrain.ts";

const FULL: TerrainPayload = {
  pooling: { level: "low", reason: "Water drains away from here (wetness index 6.3)." },
  sun: { facing: "east", label: "morning sun" },
  shelter: { level: "sheltered", reason: "Lies lower than the ground around it, out of the wind." },
  view: { area_km2: 4.2, direction: "east", water: true },
  has_viewshed: true,
  note: TERRAIN_NOTE,
};

test("a site with every fact gets four lines in order, worded as the panel shows them", () => {
  const lines = terrainLines(FULL);
  assert.deepEqual(
    lines.map((l) => [l.label, l.value]),
    [
      ["Water pooling risk", "low"],
      ["Sun", "Faces east: morning sun"],
      ["Wind", "Sheltered"],
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
    view: { area_km2: null, direction: null, water: null },
  });
  assert.deepEqual(
    lines.map((l) => l.key),
    ["pooling"],
  );
  const noWater = terrainLines({ ...FULL, view: { area_km2: 0.35, direction: "all around", water: false } });
  assert.equal(noWater.at(-1)!.value, "0.35 km², all around");
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
