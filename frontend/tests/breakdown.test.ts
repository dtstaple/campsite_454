/**
 * TM05-47: the campsite panel's score breakdown. The four cases from the story -- scored,
 * partially available, no score at all, malformed -- plus the contract's edge cases
 * (docs/scoring.md, "Edge cases consumers must handle").
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { breakdownView, parseScore, type BreakdownView } from "../src/score/breakdown.ts";
import { selectionFromFeature } from "../src/campsite/selection.ts";

/** A contract-1 score shaped exactly like backend/scoring/engine.py's output. */
function score(overrides: Record<string, unknown> = {}, factors?: unknown[]) {
  return {
    contract: 1,
    model_version: "1.2.0",
    config_digest: "a33b94ce",
    location: { lon: -73.9512, lat: 44.1847 },
    score: 81,
    factors: factors ?? [
      {
        key: "water", label: "Water", status: "scored", score: 96.2, weight: 0.35,
        effective_weight: 0.3182, contribution: 30.6,
        measurement: {
          distance_m: 62.4, ideal_m: 60, feature_type: "stream", perennial: true,
          name: "Johns Brook", source: "nhd", source_id: "22300012", nearest_any_m: 62.4,
        },
        explanation: "Perennial stream 62 m away (ideal is about 60 m).",
      },
      {
        key: "legal", label: "Legal status", status: "scored", score: 100, weight: 0.3,
        effective_weight: 0.2727, contribution: 27.3,
        measurement: {
          public_access: "open", gap_status: "1", manager: "NYS DEC",
          designation: "Wilderness", parcels: 1,
        },
        explanation: "Open public land (Wilderness).",
      },
      {
        key: "trail", label: "Trail access", status: "scored", score: 44.1, weight: 0.2,
        effective_weight: 0.1818, contribution: 8.0,
        measurement: { distance_m: 1004, ideal_m: 60, name: "Van Hoevenberg Trail", trail_type: "path" },
        explanation: "Nearest trail 1.0 km away.",
      },
      {
        key: "weather", label: "Weather", status: "scored", score: 80, weight: 0.15,
        effective_weight: 0.1364, contribution: 10.9,
        measurement: {
          date: "2026-10-06", precipitation_mm: 5, wind_max_kmh: 22, temperature_min_c: 3.4,
        },
        explanation: "5 mm of rain forecast.",
      },
      {
        key: "slope", label: "Slope", status: "scored", score: 75, weight: 0.1,
        effective_weight: 0.0909, contribution: 6.8,
        measurement: { slope_deg: 5.6, slope_pct: 9.8, elevation_m: 721 },
        explanation: "Ground is gently sloping: 6° (10%) across 20 m.",
      },
      {
        key: "land_cover", label: "Land cover", status: "not_available", score: null, weight: 0.05,
        effective_weight: 0, contribution: 0, measurement: null,
        explanation: "Land cover is not measured yet (planned: Sentinel-2, Sprint 5).",
      },
    ],
    caps: [],
    ...overrides,
  };
}

function scored(view: BreakdownView) {
  assert.equal(view.kind, "scored");
  return view as Extract<BreakdownView, { kind: "scored" }>;
}

const row = (view: ReturnType<typeof scored>, key: string) => {
  const found = view.rows.find((r) => r.key === key);
  assert.ok(found, key);
  return found;
};

test("scored: the total leads, with its grade", () => {
  const view = scored(breakdownView(score()));
  assert.equal(view.score, 81);
  assert.equal(view.grade, "B");
  assert.deepEqual(view.caps, []);
});

test("scored: every factor has its sub-score and the measurement in plain words", () => {
  const view = scored(breakdownView(score()));
  assert.deepEqual(
    view.rows.map((r) => [r.label, r.value, r.detail]),
    [
      ["Water", "96", "62 m from perennial stream (Johns Brook)"],
      ["Legal status", "100", "Open to the public · Wilderness"],
      ["Trail access", "44", "0.6 mi from Van Hoevenberg Trail"],
      ["Weather", "80", "Forecast for 2026-10-06: 5.0 mm rain, wind to 22 km/h, low 3 °C"],
      ["Slope", "75", "Ground slope 6° (10%)"],
      ["Land cover", "Not available", "Land cover is not measured yet (planned: Sentinel-2, Sprint 5)."],
    ],
  );
});

test("partially available: missing factors read 'Not available', never 0, and take no grade", () => {
  const base = score();
  const factors = base.factors.map((f) =>
    f.key === "weather" || f.key === "slope"
      ? { ...f, status: "not_available", score: null, effective_weight: 0, contribution: 0,
          measurement: null, explanation: `${f.label} source unreachable.` }
      : f,
  );
  const view = scored(breakdownView(score({ score: 74 }, factors)));
  assert.equal(view.missing, 3); // weather, slope, land cover
  for (const key of ["weather", "slope", "land_cover"]) {
    const missing = row(view, key);
    assert.equal(missing.value, "Not available");
    assert.notEqual(missing.value, "0");
    assert.equal(missing.grade, null);
    assert.equal(missing.status, "not_available");
  }
  assert.equal(row(view, "weather").detail, "Weather source unreachable.");
  assert.equal(row(view, "water").value, "96"); // the rest still render
});

test("partially available: a not_available factor that still carries a number is not shown as one", () => {
  const factors = score().factors.map((f) => (f.key === "land_cover" ? { ...f, score: 0 } : f));
  assert.equal(row(scored(breakdownView(score({}, factors))), "land_cover").value, "Not available");
});

test("no_data is real information: its low score is shown, with what was looked for", () => {
  const factors = score().factors.map((f) =>
    f.key === "water"
      ? { ...f, status: "no_data", score: 0, measurement: { distance_m: null, max_search_m: 3000 } }
      : f.key === "legal"
        ? { ...f, status: "no_data", score: 15, measurement: { public_access: null, parcels: 0 } }
        : f,
  );
  const view = scored(breakdownView(score({ score: 52 }, factors)));
  assert.deepEqual([row(view, "water").value, row(view, "water").detail], ["0", "No water within 1.9 mi"]);
  assert.deepEqual([row(view, "legal").value, row(view, "legal").detail], ["15", "Not inside any mapped public land"]);
});

test("a capped score of 0 says why", () => {
  const view = scored(
    breakdownView(score({ score: 0, caps: [{ factor: "legal", max_score: 0, reason: "Inside land marked closed to the public." }] })),
  );
  assert.equal(view.score, 0);
  assert.equal(view.grade, "F");
  assert.deepEqual(view.caps, ["Inside land marked closed to the public."]);
});

test("no score at all: the panel gets 'none', not a 0", () => {
  assert.deepEqual(breakdownView(null), { kind: "none" });
  assert.deepEqual(breakdownView(undefined, null), { kind: "none" });
});

test("a bare total with no breakdown shows the total, breakdown pending", () => {
  assert.deepEqual(breakdownView(null, 88), { kind: "total-only", score: 88, grade: "B" });
});

test("malformed: anything that is not a contract-1 score is treated as no score", () => {
  const malformed: unknown[] = [
    "not json {",
    42,
    [],
    {},
    { score: 81, factors: [] }, // no contract
    score({ contract: 2 }), // a future, breaking contract
    score({ score: "81" }),
    score({ score: null }),
    score({ factors: "water" }),
  ];
  for (const raw of malformed) {
    assert.deepEqual(breakdownView(raw), { kind: "none" }, JSON.stringify(raw));
    assert.equal(parseScore(raw), null);
  }
});

test("malformed factors are dropped, unknown factors still read, the rest render", () => {
  const view = scored(
    breakdownView(
      score({}, [
        null,
        { key: "water", status: "bogus" },
        { label: "No key", status: "scored", score: 50 },
        { key: "noise", label: "Noise", status: "scored", score: 70, measurement: { db: 30 }, explanation: "Quiet at night." },
        { key: "trail", label: "Trail access", status: "scored", score: 90, measurement: { distance_m: "far" }, explanation: "Trail nearby." },
      ]),
    ),
  );
  assert.deepEqual(
    view.rows.map((r) => [r.key, r.value, r.detail]),
    [
      ["noise", "70", "Quiet at night."],
      ["trail", "90", "Trail nearby."],
    ],
  );
});

test("a breakdown on a map feature arrives as a JSON string and still parses", () => {
  const feature = {
    properties: { name: "Site", score: 81, score_breakdown: JSON.stringify(score()) },
    geometry: { type: "Point", coordinates: [-73.95, 44.18] },
  };
  const selection = selectionFromFeature(feature, "node/1");
  assert.equal(scored(breakdownView(selection?.breakdown, selection?.score)).score, 81);
});
