import { test } from "node:test";
import assert from "node:assert/strict";
import { draftFor, emptyDraft, nights, planFilename, toggleStop, trailRef } from "../src/plans/draft.ts";

test("a draft belongs to one trail; another trail starts empty", () => {
  const draft = { trailKey: "relation/1", stopIds: ["node/1"], planId: 7, name: "Weekend" };
  assert.equal(draftFor(draft, "relation/1"), draft);
  assert.deepEqual(draftFor(draft, "relation/2"), emptyDraft("relation/2"));
  assert.deepEqual(draftFor(null, "relation/2"), emptyDraft("relation/2"));
});

test("toggling adds a stop, and toggling again takes it out", () => {
  const added = toggleStop(emptyDraft("relation/1"), "node/1");
  assert.deepEqual(added.stopIds, ["node/1"]);
  assert.deepEqual(toggleStop(toggleStop(added, "node/2"), "node/1").stopIds, ["node/2"]);
});

test("the trail is named by route, or by the way an assembled trail came from", () => {
  assert.deepEqual(trailRef({ osm_id: 5 }), { osm_id: 5 });
  assert.deepEqual(trailRef({ osm_id: null, assembly: { from_way: "way/9" } }), { from_way: "way/9" });
  assert.equal(trailRef({ osm_id: null, assembly: null }), null);
});

test("nights and file names read naturally", () => {
  assert.equal(nights(1), "1 night");
  assert.equal(nights(2), "2 nights");
  assert.equal(planFilename("Marcy: 2 nights"), "marcy-2-nights.gpx");
  assert.equal(planFilename("!!!"), "plan.gpx");
});
