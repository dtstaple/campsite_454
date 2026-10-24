import { test } from "node:test";
import assert from "node:assert/strict";
import { setZoneVisible, ZONE_MAX_ZOOM, ZONES, zoneLayerIds, zoneSource } from "../src/terrain/zones.ts";

test("two overlays, Water pooling risk and Exposure, each a fill and an outline", () => {
  assert.deepEqual(
    ZONES.map((z) => [z.id, z.label]),
    [
      ["pooling-risk", "Water pooling risk"],
      ["exposure", "Exposure"],
    ],
  );
  assert.deepEqual(zoneLayerIds("exposure"), ["terrain-exposure-fill", "terrain-exposure-line"]);
  for (const zone of ZONES) assert.match(zone.token, /^--terrain-/); // theme.css tokens only
});

test("zone sources read the tile endpoint from the backend's minzoom to the tile max", () => {
  for (const zone of ZONES) {
    const source = zoneSource("http://api", zone);
    assert.equal(source.type, "vector");
    assert.deepEqual(source.tiles, [`http://api/api/tiles/${zone.id}/{z}/{x}/{y}.mvt`]);
    assert.equal(source.minzoom, 8); // backend/api/tiles.py TileLayer minzoom
    assert.equal(source.maxzoom, ZONE_MAX_ZOOM);
  }
});

function fakeMap(layers: string[]) {
  const visibility = new Map<string, string>();
  return {
    visibility,
    getLayer: (id: string) => (layers.includes(id) ? { id } : undefined),
    setLayoutProperty: (id: string, _name: "visibility", value: string) => visibility.set(id, value),
  };
}

test("toggling a zone overlay shows or hides both its layers and nothing else", () => {
  const map = fakeMap([...zoneLayerIds("pooling-risk"), ...zoneLayerIds("exposure")]);
  setZoneVisible(map, "pooling-risk", true);
  assert.deepEqual(Object.fromEntries(map.visibility), {
    "terrain-pooling-risk-fill": "visible",
    "terrain-pooling-risk-line": "visible",
  });
  setZoneVisible(map, "pooling-risk", false);
  assert.equal(map.visibility.get("terrain-pooling-risk-fill"), "none");
  assert.equal(map.visibility.has("terrain-exposure-fill"), false);
});

test("a toggle before the layers exist does nothing", () => {
  const map = fakeMap([]);
  setZoneVisible(map, "exposure", true);
  assert.equal(map.visibility.size, 0);
});
