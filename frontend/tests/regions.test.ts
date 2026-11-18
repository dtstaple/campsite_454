import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// TM05-173: the region picker lists the Western pilot, with the box regions.yml ingests.
// src/regions.ts imports "./api" without an extension, which node's test runner cannot
// resolve, so its REGIONS entries are read from the source.
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const REGIONS_TS = read("../src/regions.ts");
const REGIONS_YML = read("../../backend/pipeline/regions.yml");

const picker = [
  ...REGIONS_TS.matchAll(/\{ id: "([^"]+)", label: "[^"]+", bbox: \[([^\]]+)\] \}/g),
].map(([, id, bbox]) => ({ id, bbox: bbox.split(",").map(Number) }));

function ymlBbox(id: string): number[] {
  const block = REGIONS_YML.split(`\n  ${id}:\n`)[1];
  assert.ok(block, `${id} is not in regions.yml`);
  const match = block.match(/bbox: \[([^\]]+)\]/);
  assert.ok(match, `${id} has no bbox in regions.yml`);
  return match[1].split(",").map(Number);
}

test("the picker keeps the Northeast regions and adds the Front Range pilot", () => {
  assert.deepEqual(
    picker.map((r) => r.id),
    ["adirondacks", "white-mountains-nh", "front-range-co"],
  );
});

test("every picker region uses the bbox regions.yml ingests", () => {
  for (const region of picker) {
    assert.deepEqual(region.bbox, ymlBbox(region.id), region.id);
  }
});
