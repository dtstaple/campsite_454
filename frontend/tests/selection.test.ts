/**
 * TM05-69: the selected campsite. Where the camera goes, how much room the panel gets,
 * and what the pin says -- the parts of the 3D highlight that are decisions, not drawing.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  SELECTED_PITCH,
  SELECTED_ZOOM,
  panelPadding,
  pinColorToken,
  pinLabel,
  selectionCamera,
  selectionFromFeature,
} from "../src/campsite/selection.ts";

const MAP = { left: 0, top: 0, right: 1440, bottom: 860 };
const MARGIN = 48;

test("a side column panel pads the right by its width plus the gap to the edge", () => {
  // trails.css: 360 px wide, 12 px in from the right edge.
  const panel = { left: 1068, top: 12, right: 1428, bottom: 848 };
  assert.deepEqual(panelPadding(MAP, panel, MARGIN), {
    top: MARGIN,
    right: 1440 - 1068 + MARGIN,
    bottom: MARGIN,
    left: MARGIN,
  });
});

test("a bottom sheet panel (phone) pads the bottom instead", () => {
  const phone = { left: 0, top: 0, right: 390, bottom: 760 };
  const sheet = { left: 12, top: 340, right: 378, bottom: 748 };
  const padding = panelPadding(phone, sheet, MARGIN);
  assert.equal(padding.right, MARGIN);
  assert.equal(padding.bottom, 760 - 340 + MARGIN);
});

test("no panel in the DOM still gives an even margin", () => {
  assert.deepEqual(panelPadding(MAP, null, MARGIN), {
    top: MARGIN,
    right: MARGIN,
    bottom: MARGIN,
    left: MARGIN,
  });
});

// Right 420 for the panel, 48 elsewhere: the site moves (48 - 420) / 2 = -186 px left.
const PADDING = { top: 48, right: 420, bottom: 48, left: 48 };
const OFFSET = [-186, 0];

test("in 3D the camera keeps the bearing, tilts to 60 and comes in to 15.5", () => {
  const camera = selectionCamera({ zoom: 12, bearing: -37, terrain: true }, [-74, 44], PADDING);
  assert.deepEqual(camera, {
    center: [-74, 44],
    offset: OFFSET,
    bearing: -37,
    pitch: SELECTED_PITCH,
    zoom: SELECTED_ZOOM,
  });
});

test("in 3D a user who is already closer keeps their zoom", () => {
  const camera = selectionCamera({ zoom: 17.2, bearing: 0, terrain: true }, [-74, 44], PADDING);
  assert.equal(camera.zoom, 17.2);
});

test("in 2D the camera only re-centres: no zoom, pitch or bearing change", () => {
  const camera = selectionCamera({ zoom: 11, bearing: 20, terrain: false }, [-74, 44], PADDING);
  assert.deepEqual(camera, { center: [-74, 44], offset: OFFSET });
});

test("the panel room is an offset, never padding, so it cannot outlive the move", () => {
  const camera = selectionCamera({ zoom: 11, bearing: 0, terrain: true }, [-74, 44], PADDING);
  assert.equal("padding" in camera, false);
});

test("the pin label falls back to 'Campsite' and rounds the score", () => {
  assert.deepEqual(pinLabel("Marcy Dam", 98.6), { name: "Marcy Dam", score: "99" });
  assert.deepEqual(pinLabel(null, null), { name: "Campsite", score: null });
});

test("the pin head uses the grade token, or the neutral one with no score", () => {
  assert.equal(pinColorToken(88), "--score-b");
  assert.equal(pinColorToken(null), "--score-none");
  assert.equal(pinColorToken(0), "--score-f");
});

test("a map feature becomes a selection; a missing score stays null, not 0", () => {
  const feature = {
    properties: { name: "", site_type: "primitive" },
    geometry: { type: "Point", coordinates: [-73.99, 44.11] },
  };
  assert.deepEqual(selectionFromFeature(feature, "node/4211004793"), {
    id: "node/4211004793",
    lon: -73.99,
    lat: 44.11,
    name: null,
    score: null,
  });
  assert.equal(selectionFromFeature(feature, ""), null);
});
