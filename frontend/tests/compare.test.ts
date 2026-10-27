import { test } from "node:test";
import assert from "node:assert/strict";
import {
  COMPARE_MAX,
  addTrail,
  compareRows,
  fromDetail,
  fromHit,
  isCompared,
  isFull,
  parseCompared,
  removeTrail,
  type ComparedTrail,
} from "../src/trails/compare.ts";
import type { RouteDetail, RouteHit } from "../src/trails/api.ts";

function trail(id: number, extra: Partial<ComparedTrail> = {}): ComparedTrail {
  return {
    key: `relation/${id}`,
    target: { osmId: id },
    name: `Trail ${id}`,
    length_m: 1609.344 * id,
    gain_m: 100,
    difficulty: "easy",
    route_type: "loop",
    route_type_estimated: false,
    campsites: 0,
    campsites_within_m: 500,
    ...extra,
  };
}

test("trails are added in order", () => {
  let list: ComparedTrail[] = [];
  for (const id of [1, 2]) {
    const result = addTrail(list, trail(id));
    assert.equal(result.status, "added");
    list = result.list;
  }
  assert.deepEqual(list.map((t) => t.key), ["relation/1", "relation/2"]);
  assert.ok(isCompared(list, "relation/2"));
  assert.ok(!isCompared(list, "relation/3"));
});

test("adding a trail twice keeps one copy", () => {
  const list = addTrail([], trail(1)).list;
  const again = addTrail(list, trail(1));
  assert.equal(again.status, "already");
  assert.equal(again.list.length, 1);
});

test("a fourth trail is refused and the three stay", () => {
  assert.equal(COMPARE_MAX, 3);
  const three = [trail(1), trail(2), trail(3)];
  assert.ok(isFull(three));
  const result = addTrail(three, trail(4));
  assert.equal(result.status, "full");
  assert.deepEqual(result.list.map((t) => t.key), ["relation/1", "relation/2", "relation/3"]);
  // Removing one makes room again.
  const room = removeTrail(three, "relation/2");
  assert.ok(!isFull(room));
  assert.equal(addTrail(room, trail(4)).status, "added");
});

test("removing a trail leaves the others in order, and adding never mutates", () => {
  const list = [trail(1), trail(2), trail(3)];
  assert.deepEqual(removeTrail(list, "relation/2").map((t) => t.key), ["relation/1", "relation/3"]);
  assert.deepEqual(removeTrail(list, "relation/9").length, 3);
  assert.equal(list.length, 3);
  const original: ComparedTrail[] = [];
  addTrail(original, trail(1));
  assert.equal(original.length, 0);
});

test("a Discover card becomes a compared trail", () => {
  const hit: RouteHit = {
    osm_id: 42,
    name: "Van Hoevenberg",
    length_m: 11426.3,
    gain_m: 1007.4,
    centroid: [-73.95, 44.15],
    distance_m: null,
    difficulty: "hard",
    route_type: "out_and_back",
    route_type_estimated: true,
    campsites: 3,
    campsites_within_m: 500,
  };
  const compared = fromHit(hit);
  assert.equal(compared.key, "relation/42");
  assert.deepEqual(compared.target, { osmId: 42 });
  assert.equal(compared.campsites, 3);
});

function detail(extra: Partial<RouteDetail>): RouteDetail {
  return {
    osm_id: 7,
    source_id: "relation/7",
    name: "Northville-Placid",
    ref: null,
    network: null,
    operator: null,
    length_m: 5000,
    geometry: { type: "MultiLineString", coordinates: [] },
    line: { type: "LineString", coordinates: [], length_m: 5000 },
    path: { parts: 1, parts_used: 1, parts_left_out: 0, left_out_m: 0 },
    profile: { status: "unavailable", reason: "no DEM" },
    campsites: { within_m: 1000, count: 2, truncated: false, items: [] },
    ...extra,
  };
}

test("the open trail becomes a compared trail; a planned route does not", () => {
  const route = fromDetail(detail({}))!;
  assert.deepEqual(route.target, { osmId: 7 });
  assert.equal(route.gain_m, null);
  assert.equal(route.campsites_within_m, 1000);

  const assembled = fromDetail(
    detail({ osm_id: null, source_id: "assembled/way/9", assembly: { from_way: "way/9", ways: 3, note: "" } }),
  )!;
  assert.equal(assembled.key, "assembled/way/9");
  assert.deepEqual(assembled.target, { wayId: "way/9" });

  assert.equal(fromDetail(detail({ osm_id: null, source_id: "planned/x", planned: {} as RouteDetail["planned"] })), null);
});

test("the rows read distance, gain, difficulty, type, time and campsites", () => {
  const rows = compareRows([
    trail(1, { length_m: 11426.3, gain_m: 200, difficulty: "hard", route_type: "out_and_back", route_type_estimated: true, campsites: 3 }),
    trail(2, { gain_m: null, difficulty: null, route_type: null, campsites: 1, campsites_within_m: 1000 }),
  ]);
  assert.deepEqual(rows.map((r) => r.label), ["Distance", "Gain", "Difficulty", "Route type", "Est. time", "Campsites"]);
  const value = (label: string) => rows.find((r) => r.label === label)!.values;
  assert.deepEqual(value("Distance"), ["7.1 mi", "2.0 mi"]);
  assert.deepEqual(value("Gain"), ["656 ft", "Not measured yet"]);
  assert.deepEqual(value("Difficulty"), ["Hard", "—"]);
  assert.deepEqual(value("Route type"), ["Out & back (est.)", "—"]);
  // Naismith: 11.43 km at 5 km/h (137 min) + 200 m at 600 m/h (20 min), to the nearest 5.
  assert.deepEqual(value("Est. time"), ["2 h 35 min", "Not measured yet"]);
  assert.deepEqual(value("Campsites"), ["3 campsites within 500 m", "1 campsite within 1 km"]);
});

test("stored lists are read back defensively", () => {
  assert.deepEqual(parseCompared(null), []);
  assert.deepEqual(parseCompared("not json"), []);
  assert.deepEqual(parseCompared('{"key":"x"}'), []);
  const stored = JSON.stringify([trail(1), { key: "bad" }, trail(1), trail(2), trail(3), trail(4)]);
  assert.deepEqual(parseCompared(stored).map((t) => t.key), ["relation/1", "relation/2", "relation/3"]);
});
