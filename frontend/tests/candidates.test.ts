import { test } from "node:test";
import assert from "node:assert/strict";
import { alongResults, candidatesPath, searchSummary, type Candidate } from "../src/trails/candidates.ts";

const site = (id: string, along: number) => ({ id, distance_along_m: along }) as never;
const candidate = (id: string, along: number) =>
  ({ id, kind: "candidate", distance_along_m: along, label: "Potential spot (unverified)" }) as Candidate;

test("mapped campsites and candidates are merged by mile", () => {
  const rows = alongResults([site("node/1", 3000), site("node/2", 500)], [candidate("candidate/a", 1500)]);
  assert.deepEqual(rows.map((r) => [r.kind, r.id]), [
    ["campsite", "node/2"],
    ["candidate", "candidate/a"],
    ["campsite", "node/1"],
  ]);
});

test("the summary counts both, and says when the search is unavailable", () => {
  assert.equal(searchSummary(2, null), "2 mapped campsites");
  const ok = { status: "ok", within_m: 500, candidates: [candidate("c", 1)], counts: null, reason: null } as const;
  assert.equal(searchSummary(1, { ...ok, candidates: [...ok.candidates] }), "1 mapped campsite and 1 potential spot.");
  assert.match(searchSummary(0, { ...ok, candidates: [], status: "unavailable" }), /unavailable/);
});

test("the search follows the trail's identity", () => {
  assert.equal(candidatesPath({ osm_id: 7 }, 500), "/api/routes/7/candidates/?campsites_within_m=500");
  assert.equal(
    candidatesPath({ osm_id: null, assembly: { from_way: "way/9" } }, 1000),
    "/api/trails/way/9/candidates/?campsites_within_m=1000",
  );
  assert.equal(candidatesPath({ osm_id: null, assembly: null }, 500), null);
});
