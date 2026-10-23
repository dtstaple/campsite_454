import { test } from "node:test";
import assert from "node:assert/strict";
import {
  drawLayerVisibility,
  isTiled,
  TILE_MAX_ZOOM,
  TILED,
  tileUrl,
  vectorSource,
} from "../src/map/tileLayers.ts";

const API = "http://127.0.0.1:8000";

test("trails, water and public land are tiled; campsites stay on the GeoJSON API", () => {
  assert.deepEqual(Object.keys(TILED).sort(), ["public-land", "trails", "water"]);
  assert.equal(isTiled("trails"), true);
  assert.equal(isTiled("water"), true);
  assert.equal(isTiled("public-land"), true);
  assert.equal(isTiled("campsites"), false);
});

test("a tile URL is the API's /api/tiles/<layer>/{z}/{x}/{y}.mvt template", () => {
  assert.equal(tileUrl(API, "trails"), `${API}/api/tiles/trails/{z}/{x}/{y}.mvt`);
  // Phone mode proxies /api through Vite with an empty base: same-origin paths.
  assert.equal(tileUrl("", "public-land"), "/api/tiles/public-land/{z}/{x}/{y}.mvt");
});

test("each tiled source is a vector source bounded by its layer's minzoom and the tile max", () => {
  for (const layer of ["trails", "water", "public-land"] as const) {
    const source = vectorSource(API, layer);
    assert.equal(source.type, "vector");
    assert.deepEqual(source.tiles, [tileUrl(API, layer)]);
    assert.equal(source.minzoom, TILED[layer].minzoom);
    assert.equal(source.maxzoom, TILE_MAX_ZOOM);
  }
  // Linework keeps the zoom 9 floor (MIN_ZOOM_FOR_LINEWORK); public land shows at any zoom.
  assert.equal(TILED.trails.minzoom, 9);
  assert.equal(TILED.water.minzoom, 9);
  assert.equal(TILED["public-land"].minzoom, 0);
  // backend/api/tiles.py MAX_ZOOM: beyond it the server 404s and MapLibre overzooms.
  assert.equal(TILE_MAX_ZOOM, 14);
});

test("a layer turned off hides all of its draw layers, casings included", () => {
  assert.equal(drawLayerVisibility(false, false, false), "none");
  assert.equal(drawLayerVisibility(false, false, true), "none");
  assert.equal(drawLayerVisibility(false, true, true), "none");
});

test("a satellite-only casing shows only over imagery, and only with its layer on", () => {
  assert.equal(drawLayerVisibility(true, true, true), "visible");
  assert.equal(drawLayerVisibility(true, true, false), "none");
  // An ordinary draw layer ignores the basemap.
  assert.equal(drawLayerVisibility(true, false, false), "visible");
  assert.equal(drawLayerVisibility(true, false, true), "visible");
});
