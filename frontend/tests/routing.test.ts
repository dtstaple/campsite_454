import { test } from "node:test";
import assert from "node:assert/strict";
import { COSTS, duration, routingPath, stopLabels, withoutStop } from "../src/routing/planned.ts";
import { gpxPath } from "../src/trails/gpx.ts";
import { candidatesPath } from "../src/trails/candidates.ts";
import { savedRowFor, trailRef } from "../src/plans/draft.ts";

const ID = "adirondacks:naismith:2306094170,4252860218,2306094170";
const PLANNED = { osm_id: null, assembly: null, planned: { id: ID } };

test("a planned route's detail, candidates and GPX are under its id", () => {
  assert.equal(routingPath(ID, "", 500), `/api/routing/${ID}/?campsites_within_m=500`);
  assert.equal(routingPath(ID, "gpx", 1000), `/api/routing/${ID}/gpx/?campsites_within_m=1000`);
  assert.equal(gpxPath(PLANNED, 500), `/api/routing/${ID}/gpx/?campsites_within_m=500`);
  assert.equal(
    candidatesPath(PLANNED, 250),
    `/api/routing/${ID}/candidates/?campsites_within_m=250`,
  );
});

test("a planned route is planned by its id, and is never a saved trail", () => {
  assert.deepEqual(trailRef(PLANNED), { planned_route: ID });
  const saved = [{ id: 1, osm_id: null, from_way: null }];
  assert.equal(savedRowFor(saved, { planned_route: ID }), null);
});

test("routes and assembled trails are unchanged", () => {
  assert.deepEqual(trailRef({ osm_id: 7, planned: null }), { osm_id: 7 });
  assert.equal(gpxPath({ osm_id: 7, planned: null }, 500), "/api/routes/7/gpx/?campsites_within_m=500");
});

test("stops are labelled start, stops in order, end", () => {
  assert.deepEqual(stopLabels(0), []);
  assert.deepEqual(stopLabels(1), ["Start"]);
  assert.deepEqual(stopLabels(2), ["Start", "End"]);
  assert.deepEqual(stopLabels(4), ["Start", "Stop 1", "Stop 2", "End"]);
});

test("removing a stop keeps the others in order", () => {
  assert.deepEqual(withoutStop(["a", "b", "c"], 1), ["a", "c"]);
});

test("durations read in hours and minutes", () => {
  assert.equal(duration(50 * 60), "50 min");
  assert.equal(duration(2 * 3600), "2 h");
  assert.equal(duration(4 * 3600 + 35 * 60 + 10), "4 h 35 min");
});

test("both costs are offered, quickest first", () => {
  assert.deepEqual(
    COSTS.map((c) => c.id),
    ["naismith", "distance"],
  );
});
