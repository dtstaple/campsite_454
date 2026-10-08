import { test } from "node:test";
import assert from "node:assert/strict";
import {
  OPEN_STATE_KEY,
  campsiteRequest,
  panelFor,
  planRequest,
  requestFromState,
  trailRequest,
  waypointRequest,
} from "../src/profile/openRequest.ts";

test("a saved campsite opens the campsite panel at its position", () => {
  const request = campsiteRequest({ id: "node/1", lon: -74, lat: 44, name: "Lean-to" });
  assert.deepEqual(request, { kind: "campsite", id: "node/1", lon: -74, lat: 44, name: "Lean-to" });
  assert.equal(panelFor(request), "campsite");
});

test("a saved trail opens the trail panel, by route or by way", () => {
  const route = trailRequest({ osm_id: 7, from_way: null, name: "Route" });
  assert.deepEqual(route, { kind: "trail", trail: { osmId: 7 }, name: "Route" });
  const assembled = trailRequest({ osm_id: null, from_way: "way/9", name: "Path" });
  assert.deepEqual(assembled, { kind: "trail", trail: { wayId: "way/9" }, name: "Path" });
  assert.equal(panelFor(route!), "trail");
  assert.equal(trailRequest({ osm_id: null, from_way: null, name: "?" }), null);
});

test("a plan opens its trail's panel with the plan loaded", () => {
  const request = planRequest({ id: 3, osm_id: 7, from_way: null, trail_name: "Route" });
  assert.deepEqual(request, { kind: "plan", planId: 3, trail: { osmId: 7 }, name: "Route" });
  assert.equal(panelFor(request!), "trail");
});

test("a waypoint opens its editor", () => {
  const request = waypointRequest({ id: 5, lon: -74, lat: 44, name: "Spring" });
  assert.equal(panelFor(request), "waypoint");
});

test("requests survive the router state round trip, and junk does not", () => {
  const request = waypointRequest({ id: 5, lon: -74, lat: 44, name: "Spring" });
  assert.deepEqual(requestFromState({ [OPEN_STATE_KEY]: request }), request);
  assert.equal(requestFromState(null), null);
  assert.equal(requestFromState({ [OPEN_STATE_KEY]: { kind: "nope" } }), null);
  assert.equal(requestFromState("open"), null);
});

test("the trail panel finds a trail's saved row by route or by way", async () => {
  const { savedRowFor } = await import("../src/plans/draft.ts");
  const rows = [
    { id: 1, osm_id: 7, from_way: null, name: "Route", length_m: 1 },
    { id: 2, osm_id: null, from_way: "way/9", name: "Path", length_m: 1 },
  ];
  assert.equal(savedRowFor(rows, { osm_id: 7 })?.id, 1);
  assert.equal(savedRowFor(rows, { from_way: "way/9" })?.id, 2);
  assert.equal(savedRowFor(rows, { osm_id: 8 }), null);
});
