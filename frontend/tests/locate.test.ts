import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DENIED,
  DENIED_KEY,
  PERMISSION_DENIED,
  aboutKm,
  decide,
  distanceToRegionKm,
  forgetDenial,
  locateStart,
  type Geolocation,
} from "../src/location/locate.ts";

const REGIONS = [
  { id: "adirondacks", label: "Adirondacks", bbox: [-75.4, 43.0, -73.3, 44.9] as [number, number, number, number] },
  { id: "white-mountains-nh", label: "White Mountains", bbox: [-72.0, 43.85, -70.95, 44.55] as [number, number, number, number] },
];

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

/** A geolocation that answers with a position. */
function at(lon: number, lat: number): Geolocation & { calls: number } {
  const fake = {
    calls: 0,
    getCurrentPosition(success: (p: { coords: { longitude: number; latitude: number } }) => void) {
      fake.calls += 1;
      success({ coords: { longitude: lon, latitude: lat } });
    },
  };
  return fake;
}

/** A geolocation that fails with an error code. */
function failing(code: number): Geolocation & { calls: number } {
  const fake = {
    calls: 0,
    getCurrentPosition(_s: unknown, error: (e: { code: number }) => void) {
      fake.calls += 1;
      error({ code });
    },
  };
  return fake;
}

test("inside coverage: centre on the user, in their region", async () => {
  // Lake Placid.
  const outcome = await locateStart(at(-73.98, 44.28), memoryStorage(), REGIONS);
  assert.equal(outcome.kind, "inside");
  assert.ok(outcome.kind === "inside" && outcome.region.id === "adirondacks");
  assert.deepEqual(outcome.kind === "inside" && outcome.center, [-73.98, 44.28]);
});

test("outside coverage: centre on the user and name the nearest region", async () => {
  // Burlington, VT: between the two regions, nearer the Adirondacks' east edge.
  const burlington = await locateStart(at(-73.21, 44.48), memoryStorage(), REGIONS);
  assert.equal(burlington.kind, "outside");
  assert.ok(burlington.kind === "outside" && burlington.nearest.id === "adirondacks");
  assert.ok(burlington.kind === "outside" && burlington.distanceKm < 10);

  // Portland, ME: nearest is the White Mountains.
  const portland = decide([-70.26, 43.66], REGIONS);
  assert.ok(portland.kind === "outside" && portland.nearest.id === "white-mountains-nh");
  assert.ok(portland.kind === "outside" && portland.distanceKm > 50 && portland.distanceKm < 80);

  // Denver: far from both, still a nearest.
  const denver = decide([-104.99, 39.74], REGIONS);
  assert.ok(denver.kind === "outside" && denver.distanceKm > 2000);
});

test("denied: fall back to the default region and remember it", async () => {
  const storage = memoryStorage();
  const geolocation = failing(PERMISSION_DENIED);
  const outcome = await locateStart(geolocation, storage, REGIONS);
  assert.deepEqual(outcome, { kind: "fallback", reason: "denied" });
  assert.equal(storage.data.get(DENIED_KEY), DENIED);

  // The next load does not ask again.
  const next = await locateStart(geolocation, storage, REGIONS);
  assert.deepEqual(next, { kind: "fallback", reason: "remembered-denial" });
  assert.equal(geolocation.calls, 1);

  // Until the user asks to be located after all.
  forgetDenial(storage);
  await locateStart(geolocation, storage, REGIONS);
  assert.equal(geolocation.calls, 2);
});

test("unavailable or timed out: fall back, but ask again next time", async () => {
  const storage = memoryStorage();
  for (const code of [2, 3]) {
    const outcome = await locateStart(failing(code), storage, REGIONS);
    assert.deepEqual(outcome, { kind: "fallback", reason: "unavailable" });
  }
  assert.equal(storage.data.has(DENIED_KEY), false);
});

test("no geolocation at all (an old browser, or plain HTTP): fall back", async () => {
  assert.deepEqual(await locateStart(undefined, memoryStorage(), REGIONS), {
    kind: "fallback",
    reason: "unsupported",
  });
});

test("storage that throws (a private window) never breaks the start", async () => {
  const broken = {
    getItem: () => {
      throw new Error("denied");
    },
    setItem: () => {
      throw new Error("denied");
    },
    removeItem: () => {
      throw new Error("denied");
    },
  };
  assert.deepEqual(await locateStart(failing(PERMISSION_DENIED), broken, REGIONS), {
    kind: "fallback",
    reason: "denied",
  });
  forgetDenial(broken);
});

test("distances read as rough figures", () => {
  assert.equal(distanceToRegionKm([-74, 44], REGIONS[0]), 0);
  assert.equal(aboutKm(2), "about 5 km");
  assert.equal(aboutKm(63), "about 65 km");
  assert.equal(aboutKm(2234), "about 2,230 km");
});
