/**
 * TM05-63: saving a campsite from the map sent POST /api/saved-campsites/0/.
 *
 * Run with `npm test` (node --test, no dependencies). The "MapLibre round trip" below
 * reproduces what MapLibre does to GeoJSON feature ids -- non-numeric strings do not
 * survive, numeric ones do -- which is the behaviour the old popup code missed.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { sourceIdOf, withSourceIds } from "../src/map/featureIds.ts";

/** What a click hands back: MapLibre keeps numeric ids only; properties verbatim. */
function asMapLibreReturnsIt(feature: { id?: string | number; properties: object }) {
  const numeric = typeof feature.id === "number" ? feature.id : Number(feature.id);
  return { id: Number.isFinite(numeric) ? numeric : 0, properties: { ...feature.properties } };
}

const apiCampsite = {
  type: "Feature" as const,
  id: "node/5759412256",
  geometry: { type: "Point" as const, coordinates: [-74.23, 43.85] },
  properties: { name: "", site_type: "primitive" },
};

test("the old way: reading feature.id after MapLibre gives a useless id", () => {
  const clicked = asMapLibreReturnsIt(apiCampsite);
  assert.equal(String(clicked.id ?? ""), "0"); // -> POST /api/saved-campsites/0/ -> 404
});

test("the source_id survives the round trip as a property", () => {
  const [prepared] = withSourceIds({ type: "FeatureCollection", features: [apiCampsite] })
    .features;
  const clicked = asMapLibreReturnsIt(prepared);
  assert.equal(sourceIdOf(clicked), "node/5759412256");
});

test("every id shape the API produces round-trips", () => {
  for (const id of ["node/5759412256", "way/1305981156", "campsite/104324"]) {
    const [prepared] = withSourceIds({
      type: "FeatureCollection",
      features: [{ ...apiCampsite, id }],
    }).features;
    assert.equal(sourceIdOf(asMapLibreReturnsIt(prepared)), id);
  }
});

test("a feature with no id yields an empty source_id, not a fake one", () => {
  const [prepared] = withSourceIds({
    type: "FeatureCollection",
    features: [{ ...apiCampsite, id: undefined }],
  }).features;
  assert.equal(sourceIdOf(prepared), "");
});

test("existing properties are kept", () => {
  const [prepared] = withSourceIds({ type: "FeatureCollection", features: [apiCampsite] })
    .features;
  assert.equal(prepared.properties?.site_type, "primitive");
});
