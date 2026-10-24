import { test } from "node:test";
import assert from "node:assert/strict";
import {
  FACTORS,
  allZero,
  sameSliders,
  setWeight,
  shares,
  showPreferences,
  toRequest,
  toSliders,
  type Sliders,
} from "../src/profile/weights.ts";

const DEFAULTS = {
  water: 0.35,
  legal: 0.3,
  trail: 0.2,
  weather: 0.15,
  slope: 0.1,
  land_cover: 0.05,
  // TM05-143: the terrain factors.
  drainage: 0.1,
  shelter: 0.05,
  view: 0.05,
};
const TERRAIN = { drainage: 10, shelter: 5, view: 5 };

test("load: saved weights become slider positions, one per factor", () => {
  const sliders = toSliders({ ...DEFAULTS, water: 0.5, slope: 0.2 }, DEFAULTS);
  assert.deepEqual(sliders, { water: 50, legal: 30, trail: 20, weather: 15, slope: 20, land_cover: 5, ...TERRAIN });
  assert.deepEqual(Object.keys(sliders), FACTORS.map((factor) => factor.key));
});

test("load: a factor missing from the saved weights uses its default", () => {
  assert.equal(toSliders({ water: 0.5 }, DEFAULTS).trail, 20);
});

test("save: slider positions become the PUT body the API expects", () => {
  const body = toRequest({ water: 50, legal: 30, trail: 20, weather: 15, slope: 20, land_cover: 0, ...TERRAIN });
  assert.deepEqual(body, {
    weights: {
      water: 0.5,
      legal: 0.3,
      trail: 0.2,
      weather: 0.15,
      slope: 0.2,
      land_cover: 0,
      drainage: 0.1,
      shelter: 0.05,
      view: 0.05,
    },
  });
});

test("save then load round-trips", () => {
  const sliders: Sliders = { water: 7, legal: 0, trail: 100, weather: 33, slope: 1, land_cover: 64, ...TERRAIN };
  assert.deepEqual(toSliders(toRequest(sliders).weights), sliders);
});

test("reset: the defaults become the shipped slider positions", () => {
  const custom = toSliders({ ...DEFAULTS, water: 1 });
  const reset = toSliders(DEFAULTS);
  assert.equal(sameSliders(custom, reset), false);
  assert.deepEqual(reset, { water: 35, legal: 30, trail: 20, weather: 15, slope: 10, land_cover: 5, ...TERRAIN });
});

test("the all-zero state is unreachable from the sliders", () => {
  let sliders = toSliders(DEFAULTS);
  for (const { key } of FACTORS) sliders = setWeight(sliders, key, 0);
  assert.equal(allZero(sliders), false);
  assert.equal(sliders.view, 1, "the last factor stops at 1");
  // Raising another factor frees the last one to go to zero.
  sliders = setWeight(sliders, "water", 40);
  sliders = setWeight(sliders, "view", 0);
  assert.equal(sliders.view, 0);
  assert.equal(allZero(sliders), false);
});

test("slider values are clamped to whole numbers in 0-100", () => {
  const sliders = toSliders(DEFAULTS);
  assert.equal(setWeight(sliders, "water", 150).water, 100);
  assert.equal(setWeight(sliders, "water", -5).water, 0);
  assert.equal(setWeight(sliders, "water", 12.6).water, 13);
  assert.equal(setWeight(sliders, "water", Number.NaN).water, 0);
});

test("shares show each factor's part of the score", () => {
  const result = shares({
    water: 50,
    legal: 50,
    trail: 0,
    weather: 0,
    slope: 0,
    land_cover: 0,
    drainage: 0,
    shelter: 0,
    view: 0,
  });
  assert.equal(result.water, 50);
  assert.equal(result.trail, 0);
});

test("the section is hidden when signed out", () => {
  assert.equal(showPreferences(null), false);
  assert.equal(showPreferences({ token: "abc", username: "hiker" }), true);
});
