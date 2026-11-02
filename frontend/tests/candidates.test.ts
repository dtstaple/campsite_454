import { test } from "node:test";
import assert from "node:assert/strict";
import {
  alongResults,
  candidatesPath,
  searchSummary,
  signedPoints,
  terrainSummary,
  type Candidate,
} from "../src/trails/candidates.ts";

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

test("TM05-153: a candidate's row sums up the terrain that ranked it", () => {
  const reasons = [
    { key: "shelter", label: "Sheltered: lower than the ground around it", points: 8 },
    { key: "damp", label: "Damp ground: water collects nearby", points: -8 },
    { key: "view", label: "High ground: likely a view", points: 3 },
  ];
  assert.equal(terrainSummary({ terrain_reasons: reasons.slice(0, 1) }), "Terrain +8: sheltered");
  assert.equal(
    terrainSummary({ terrain_reasons: reasons }),
    "Terrain +3: sheltered, damp ground, high ground",
  );
  assert.equal(terrainSummary({ terrain_reasons: [] }), null);
  assert.equal(terrainSummary({}), null); // an older API
});

test("TM05-153: points read with a real minus sign", () => {
  assert.equal(signedPoints(8), "+8");
  assert.equal(signedPoints(-5), "−5");
  assert.equal(signedPoints(0.2), "0");
});
