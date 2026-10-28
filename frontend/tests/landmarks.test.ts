/**
 * TM05-122: peak and trailhead labels.
 *
 * Run with `npm test` (node --test, no dependencies).
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import type { FeatureCollection } from "geojson";
import {
  elevationDetail,
  elevationLabel,
  LABEL_PROPERTY,
  metresToFeet,
  PEAK_MIN_ZOOM,
  peakLabel,
  TRAILHEAD_MIN_ZOOM,
  trailheadLabel,
  withLabels,
} from "../src/map/landmarks.ts";

test("metres convert to whole feet", () => {
  assert.equal(metresToFeet(1629), 5344); // Mount Marcy
  assert.equal(metresToFeet(1317.4), 4322);
  assert.equal(metresToFeet(0), 0);
});

test("a peak label is the name and the elevation in feet", () => {
  assert.equal(peakLabel("Mount Marcy", 1629), "Mount Marcy · 5,344 ft");
  assert.equal(peakLabel("Giant Mountain", 1317.4), "Giant Mountain · 4,322 ft");
  assert.equal(peakLabel("  Cascade Mountain ", 1250), "Cascade Mountain · 4,101 ft");
});

test("a peak with no elevation shows just its name", () => {
  assert.equal(peakLabel("Noonmark Mountain", null), "Noonmark Mountain");
  assert.equal(peakLabel("Noonmark Mountain", undefined), "Noonmark Mountain");
  assert.equal(peakLabel("Noonmark Mountain", Number.NaN), "Noonmark Mountain");
  assert.equal(peakLabel("Noonmark Mountain", "1100"), "Noonmark Mountain");
  assert.equal(elevationLabel(null), null);
});

test("an unnamed peak shows its elevation, and one with neither shows nothing", () => {
  assert.equal(peakLabel("", 1000), "3,281 ft");
  assert.equal(peakLabel(null, 1000), "3,281 ft");
  assert.equal(peakLabel("", null), "");
});

test("a trailhead label is its trimmed name, or empty", () => {
  assert.equal(trailheadLabel(" Garden Trailhead "), "Garden Trailhead");
  assert.equal(trailheadLabel(""), "");
  assert.equal(trailheadLabel(null), "");
});

test("withLabels adds the label property to each layer's features and keeps the rest", () => {
  const peaks: FeatureCollection = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        id: "node/1",
        geometry: { type: "Point", coordinates: [-73.92, 44.11] },
        properties: { name: "Mount Marcy", elevation_m: 1629 },
      },
      {
        type: "Feature",
        id: "node/2",
        geometry: { type: "Point", coordinates: [-73.8, 44.1] },
        properties: { name: "Unknown Knob", elevation_m: null },
      },
    ],
  };
  const labelled = withLabels(peaks, "peaks");
  assert.equal(labelled.features[0].properties?.[LABEL_PROPERTY], "Mount Marcy · 5,344 ft");
  assert.equal(labelled.features[0].properties?.elevation_m, 1629);
  assert.equal(labelled.features[0].id, "node/1");
  assert.equal(labelled.features[1].properties?.[LABEL_PROPERTY], "Unknown Knob");
  // The input is not mutated.
  assert.equal(peaks.features[0].properties?.[LABEL_PROPERTY], undefined);

  const trailheads: FeatureCollection = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [-73.8, 44.2] },
        properties: { name: "Garden Trailhead" },
      },
      { type: "Feature", geometry: { type: "Point", coordinates: [-73.7, 44.2] }, properties: null },
    ],
  };
  const labelledTrailheads = withLabels(trailheads, "trailheads");
  assert.equal(labelledTrailheads.features[0].properties?.[LABEL_PROPERTY], "Garden Trailhead");
  assert.equal(labelledTrailheads.features[1].properties?.[LABEL_PROPERTY], "");
});

test("the popup elevation gives feet with the source metres, or null when missing", () => {
  assert.equal(elevationDetail(1629), "5,344 ft (1,629 m)");
  assert.equal(elevationDetail(null), null);
  assert.equal(elevationDetail(undefined), null);
});

test("peaks show from a regional zoom, trailheads once the trails are drawn", () => {
  // Trails are tiled from zoom 9 (tileLayers.ts); both landmark layers start after it.
  assert.ok(PEAK_MIN_ZOOM >= 9 && PEAK_MIN_ZOOM <= 12);
  assert.ok(TRAILHEAD_MIN_ZOOM >= PEAK_MIN_ZOOM);
});
