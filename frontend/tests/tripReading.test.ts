import { test } from "node:test";
import assert from "node:assert/strict";
import { NO_FILTERS } from "../src/trails/filters.ts";
import {
  NO_EXTRAS,
  chipsFor,
  extrasFrom,
  fallbackNote,
  filtersFrom,
  unsupportedLine,
  withoutChip,
  type Interpretation,
} from "../src/browse/tripReading.ts";

const READ: Interpretation = {
  min_length_mi: null,
  max_length_mi: 10,
  min_gain_ft: null,
  max_gain_ft: 2000,
  difficulty: ["moderate"],
  route_type: ["loop"],
  nights: 2,
  has_campsites: null,
  water_view: true,
  sheltered: null,
  region: "adirondacks",
  weights: null,
  unsupported: ["crowding"],
};

test("a reading becomes the page's own filters, as the server's search has them", () => {
  const filters = filtersFrom({ interpretation: READ, search: { campsites_within_m: "500" } });
  assert.deepEqual(filters, {
    ...NO_FILTERS,
    maxLengthMi: "10",
    maxGainFt: "2000",
    difficulty: ["moderate"],
    routeType: ["loop"],
    campsitesWithinM: 500,
  });
});

test("chips show filters first, then what is read but not searched on", () => {
  const filters = filtersFrom({ interpretation: READ, search: { campsites_within_m: "500" } });
  const chips = chipsFor(filters, extrasFrom(READ), "Adirondack Park");
  assert.deepEqual(
    chips.map((c) => [c.label, c.kind]),
    [
      ["Adirondack Park", "filter"],
      ["Under 10 mi", "filter"],
      ["Under 2000 ft climb", "filter"],
      ["Moderate", "filter"],
      ["Loop", "filter"],
      ["Campsites within 1,640 ft", "filter"],
      ["2 nights", "shown"],
      ["Water view", "shown"],
    ],
  );
});

test("removing a chip removes that filter only", () => {
  const filters = filtersFrom({ interpretation: READ, search: { campsites_within_m: "500" } });
  const extras = extrasFrom(READ);
  const next = withoutChip("difficulty:moderate", filters, extras);
  assert.deepEqual(next.filters.difficulty, []);
  assert.equal(next.filters.maxLengthMi, "10");
  assert.equal(withoutChip("length", filters, extras).filters.maxLengthMi, "");
  assert.equal(withoutChip("campsites", filters, extras).filters.campsitesWithinM, null);
  assert.equal(withoutChip("nights", filters, extras).extras.nights, null);
  assert.equal(withoutChip("water_view", filters, extras).extras.waterView, null);
});

test("ranges read naturally", () => {
  const chips = chipsFor({ ...NO_FILTERS, minLengthMi: "5", maxLengthMi: "8", minGainFt: "3000" }, NO_EXTRAS, null);
  assert.deepEqual(
    chips.map((c) => c.label),
    ["5–8 mi", "Over 3000 ft climb"],
  );
});

test("weights with a value show; all-null weights don't", () => {
  assert.equal(extrasFrom({ ...READ, weights: { water: 0.8, slope: null } }).weights?.water, 0.8);
  assert.equal(extrasFrom({ ...READ, weights: { water: null } }).weights, null);
  const chips = chipsFor(NO_FILTERS, { ...NO_EXTRAS, weights: { water: 0.8, land_cover: 0.1 } }, null);
  assert.equal(chips[0].label, "Weights: water 0.8, land cover 0.1");
});

test("unsupported asks are named back", () => {
  assert.equal(unsupportedLine("crowding"), "Crowding isn't something we can measure yet.");
  assert.equal(unsupportedLine("dog rules"), "Dog rules isn't something we can measure yet.");
});

test("the keyword fallback is noted; the model's reading is not", () => {
  assert.equal(fallbackNote({ source: "llm", fallback_reason: null }), null);
  assert.match(fallbackNote({ source: "keywords", fallback_reason: "no_key" })!, /^The AI reader isn't set up here, so a simple keyword reader/);
  assert.match(fallbackNote({ source: "keywords", fallback_reason: "timeout" })!, /took too long/);
  assert.match(fallbackNote({ source: "keywords", fallback_reason: "invalid_output" })!, /couldn't be used/);
});
