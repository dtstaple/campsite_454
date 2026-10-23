import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addFix,
  hikeStats,
  markGap,
  moving,
  pause,
  resume,
  saveBody,
  startRecording,
  stop,
  trackLines,
  walked,
  type Fix,
  type Recording,
} from "../src/tracking/track.ts";
import { TRACKING } from "../src/tracking/config.ts";
import { elevationSoFar, naiveGain, thresholdGain, trailingMean } from "../src/tracking/elevation.ts";
import {
  directionFrom,
  farFromTrailNote,
  gainLeft,
  mileOf,
  trailLine,
  trailProgress,
  type TrailSnapshot,
} from "../src/tracking/progress.ts";
import { ActiveHikeStore, memoryKeyValue } from "../src/tracking/store.ts";
import { bilinear, tilePixel } from "../src/tracking/demPixels.ts";

// Synthetic walking near Lake Placid: north is +lat. One metre of latitude, in degrees.
const LON = -73.96;
const LAT = 44.18;
const M = 1 / 111_195;
const T0 = 1_791_000_000_000;

function fix(northM: number, seconds: number, accuracyM = 5, eastM = 0): Fix {
  return { lon: LON + (eastM * M) / Math.cos((LAT * Math.PI) / 180), lat: LAT + northM * M, accuracyM, t: T0 + seconds * 1000 };
}

function begin(mode: "trail" | "free" = "free", trail: TrailSnapshot | null = null): Recording {
  return startRecording({ id: "h1", owner: "alice", mode, simulated: false, trail, now: T0 });
}

function feed(recording: Recording, fixes: Fix[], ele: (f: Fix) => number | null = () => null) {
  return fixes.reduce((r, f) => addFix(r, f, ele(f)), recording);
}

/** Walking north at `speed` m/s, one fix a second, for `seconds`, from `fromM` at `t0` s. */
function walk(seconds: number, speed = 1.3, fromM = 0, t0 = 0): Fix[] {
  return Array.from({ length: seconds + 1 }, (_, i) => fix(fromM + speed * i, t0 + i));
}

/** Standing at `atM` for `seconds`, with jitter of up to `jitterM` metres each way. */
function stand(seconds: number, atM: number, t0: number, jitterM = 3): Fix[] {
  return Array.from({ length: seconds }, (_, i) => fix(atM + jitterM * Math.sin(i * 1.7), t0 + 1 + i, 5, jitterM * Math.cos(i * 2.3)));
}

// --- distance, moving time, stops -----------------------------------------------------------

test("distance follows the walk, within a step of the truth", () => {
  const recording = feed(begin(), walk(600)); // 780 m in 10 min
  const { distanceM } = walked(recording);
  assert.ok(Math.abs(distanceM - 780) <= TRACKING.distanceStepM, `distance ${distanceM}`);
});

test("standing still with GPS jitter adds no distance and no moving time", () => {
  const recording = feed(begin(), stand(300, 0, 0, 4));
  assert.equal(walked(recording).distanceM, 0);
  const { movingMs, stops } = moving(recording, T0 + 300_000);
  assert.equal(movingMs, 0);
  assert.equal(stops.length, 1);
});

test("a stop of a minute or more comes out of moving time; a shorter pause does not", () => {
  // 5 min walking, 3 min stopped, 5 min walking, a 30 s halt, 2 min walking.
  let fixes = walk(300);
  fixes = fixes.concat(stand(180, 390, 300));
  fixes = fixes.concat(walk(300, 1.3, 390, 481));
  fixes = fixes.concat(stand(30, 780, 781));
  fixes = fixes.concat(walk(120, 1.3, 780, 812));
  const end = T0 + 932_000;
  const recording = feed(begin(), fixes);
  const motion = moving(recording, end);
  assert.equal(motion.stops.length, 1, "only the 3-minute stop");
  const stopS = (motion.stops[0].to - motion.stops[0].from) / 1000;
  assert.ok(stopS >= 170 && stopS <= 195, `stop ${stopS} s`);
  const stats = hikeStats(recording, end);
  assert.equal(stats.elapsedMs, 932_000);
  const movingS = stats.movingMs / 1000;
  assert.ok(Math.abs(movingS - (932 - 180)) <= 20, `moving ${movingS} s`);
  assert.ok(stats.movingMs < stats.elapsedMs);
  assert.ok(Math.abs(stats.distanceM - 936) <= 15, `distance ${stats.distanceM}`);
  // Pace: moving minutes per mile.
  const pace = stats.paceMinPerMi!;
  assert.ok(Math.abs(pace - movingS / 60 / (stats.distanceM / 1609.344)) < 1e-9);
});

test("standing still for a minute right now shows as stopped", () => {
  const recording = feed(begin(), walk(60).concat(stand(70, 78, 60)));
  assert.equal(moving(recording, T0 + 131_000).stoppedNow, true);
  const tenSeconds = feed(begin(), walk(60).concat(stand(10, 78, 60)));
  assert.equal(moving(tenSeconds, T0 + 71_000).stoppedNow, false);
});

test("pausing excludes the paused time and starts a new segment", () => {
  let recording = feed(begin(), walk(120));
  recording = pause(recording, T0 + 120_000);
  recording = feed(recording, walk(60, 1.3, 156, 130)); // ignored while paused
  recording = resume(recording, T0 + 600_000);
  recording = feed(recording, walk(120, 1.3, 400, 600));
  const stats = hikeStats(recording, T0 + 720_000);
  assert.equal(stats.elapsedMs, 240_000);
  assert.equal(recording.segments.map((s) => s.kind).join(","), "start,resume");
  // The jump from 156 m to 400 m while paused is not walked distance.
  assert.ok(Math.abs(stats.distanceM - 312) <= 2 * TRACKING.distanceStepM, `distance ${stats.distanceM}`);
  assert.ok(stats.movingMs <= stats.elapsedMs);
});

test("a hidden stretch is a gap in the track but still walked", () => {
  let recording = feed(begin(), walk(60));
  recording = markGap(recording);
  recording = feed(recording, walk(60, 1.3, 234, 180)); // walked 156 m unseen
  assert.equal(trackLines(recording).length, 2);
  assert.equal(recording.segments[1].kind, "gap");
  const stats = hikeStats(recording, T0 + 240_000);
  assert.ok(Math.abs(stats.distanceM - 312) <= 2 * TRACKING.distanceStepM, `distance ${stats.distanceM}`);
  assert.ok(stats.movingMs >= 230_000, `moving ${stats.movingMs}`);
});

test("stopping keeps the last position and freezes the clock", () => {
  let recording = feed(begin(), walk(9)); // 1-second fixes 1.3 m apart: not all are kept
  recording = stop(recording, T0 + 9_000);
  const points = recording.segments[0].points;
  assert.equal(points[points.length - 1].t, T0 + 9_000);
  assert.equal(hikeStats(recording, T0 + 99_000).elapsedMs, 9_000);
  assert.equal(addFix(recording, fix(50, 20), null), recording);
});

test("a jump faster than anyone walks moves the track but adds no distance", () => {
  let recording = feed(begin(), walk(60));
  recording = addFix(recording, fix(78 + 2000, 61), null); // 2 km in a second
  recording = feed(recording, walk(60, 1.3, 2078, 61));
  const { distanceM } = walked(recording);
  assert.ok(Math.abs(distanceM - 156) <= 2 * TRACKING.distanceStepM, `distance ${distanceM}`);
});

// --- dropping inaccurate fixes ---------------------------------------------------------------

test("fixes worse than the accuracy threshold are dropped and counted", () => {
  let recording = feed(begin(), walk(30));
  const before = recording.segments[0].points.length;
  recording = addFix(recording, fix(500, 31, 120), null); // a wild 120 m fix
  recording = addFix(recording, fix(40, 32, TRACKING.maxAccuracyM + 1), null);
  recording = addFix(recording, { ...fix(40, 33), accuracyM: Number.NaN }, null);
  assert.equal(recording.dropped, 3);
  assert.equal(recording.segments[0].points.length, before);
  assert.ok(walked(recording).distanceM < 45);
  recording = addFix(recording, fix(45, 34, TRACKING.maxAccuracyM), null); // at the threshold: kept
  assert.equal(recording.dropped, 3);
  assert.equal(recording.last?.t, T0 + 34_000);
});

// --- elevation smoothing ----------------------------------------------------------------------

test("smoothing keeps a steady climb and removes noise from the gain", () => {
  // 1 km climbing 100 m, sampled every 10 m, with +/-2.5 m of noise.
  const samples = Array.from({ length: 101 }, (_, i) => ({
    alongM: i * 10,
    elevationM: 500 + i + 2.5 * Math.sin(i * 2.1),
  }));
  const raw = samples.map((s) => s.elevationM);
  assert.ok(naiveGain(raw) > 150, `naive ${naiveGain(raw)}`);
  const { gainM, currentM } = elevationSoFar(samples, 100, 3);
  assert.ok(Math.abs(gainM - 95) <= 6, `gain ${gainM}`); // a trailing 100 m mean lags ~50 m
  assert.ok(Math.abs(currentM! - 595) <= 3, `current ${currentM}`);
});

test("flat ground with noise gains nothing", () => {
  const samples = Array.from({ length: 200 }, (_, i) => ({ alongM: i * 5, elevationM: 600 + 2 * Math.sin(i * 1.3) }));
  assert.equal(elevationSoFar(samples, 100, 3).gainM, 0);
});

test("the trailing mean and the threshold behave as documented", () => {
  assert.deepEqual(
    trailingMean(
      [
        { alongM: 0, elevationM: 10 },
        { alongM: 50, elevationM: 20 },
        { alongM: 120, elevationM: 30 },
      ],
      100,
    ),
    [10, 15, 25],
  );
  assert.equal(thresholdGain([0, 2, 4, 1, 5, 9], 3), 9 - 1 + (4 - 0));
  assert.equal(thresholdGain([], 3), 0);
});

test("the hike's elevation comes from the samples it was given", () => {
  const recording = feed(begin(), walk(600), (f) => 500 + (f.lat - LAT) / M / 10); // 10% grade
  const stats = hikeStats(recording, T0 + 600_000);
  assert.ok(Math.abs(stats.gainM - 73) <= 8, `gain ${stats.gainM}`);
  assert.ok(stats.elevationM! > 570 && stats.elevationM! < 580, `elevation ${stats.elevationM}`);
});

// --- mile along the trail ---------------------------------------------------------------------

/** A 3 km trail due north from (LON, LAT), with stops at 1 km and 2.5 km. */
const TRAIL: TrailSnapshot = {
  key: "relation/1",
  name: "Test Trail",
  osmId: 1,
  fromWay: null,
  coords: Array.from({ length: 31 }, (_, i) => [LON, LAT + i * 100 * M]),
  profile: {
    distances: Array.from({ length: 31 }, (_, i) => i * 100),
    elevations: Array.from({ length: 31 }, (_, i) => 500 + i * 10), // climbs 300 m
  },
  stops: [
    { id: "node/1", label: "Lean-to", kind: "campsite", alongM: 1000 },
    { id: "cand/1", label: "Potential spot", kind: "candidate", alongM: 2500 },
  ],
};
const at = (northM: number, eastM = 0): [number, number] => {
  const f = fix(northM, 0, 5, eastM);
  return [f.lon, f.lat];
};

test("the mile along the trail and the miles left", () => {
  const progress = trailProgress(TRAIL, at(1609.344), 1, { distanceM: 0, movingMs: 0 });
  assert.ok(Math.abs(progress.doneM - 1609.344) < 2);
  assert.equal(mileOf(progress), "1.0 of 1.9 mi");
  assert.ok(Math.abs(progress.leftM - (3000 - 1609.344)) < 2);
  assert.equal(progress.offTrail, false);
  assert.ok(progress.offM < 1);
});

test("walking the trail from its far end counts from that end", () => {
  const line = trailLine(TRAIL);
  assert.equal(directionFrom(line, at(2900)), -1);
  assert.equal(directionFrom(line, at(100)), 1);
  const progress = trailProgress(TRAIL, at(2000), -1, { distanceM: 0, movingMs: 0 });
  assert.ok(Math.abs(progress.doneM - 1000) < 2);
  // Ahead, walking south from 2 km: the lean-to at 1 km; the spot at 2.5 km is behind.
  assert.deepEqual(progress.ahead.map((a) => a.stop.id), ["node/1"]);
  assert.ok(Math.abs(progress.ahead[0].aheadM - 1000) < 2);
});

test("the next campsites ahead, nearest first", () => {
  const progress = trailProgress(TRAIL, at(500), 1, { distanceM: 0, movingMs: 0 });
  assert.deepEqual(progress.ahead.map((a) => a.stop.id), ["node/1", "cand/1"]);
  assert.ok(Math.abs(progress.ahead[1].aheadM - 2000) < 2);
  assert.equal(trailProgress(TRAIL, at(2600), 1, { distanceM: 0, movingMs: 0 }).ahead.length, 0);
});

test("off the trail past the warning distance", () => {
  assert.equal(trailProgress(TRAIL, at(1500, 60), 1, { distanceM: 0, movingMs: 0 }).offTrail, false);
  const off = trailProgress(TRAIL, at(1500, 120), 1, { distanceM: 0, movingMs: 0 });
  assert.equal(off.offTrail, true);
  assert.ok(Math.abs(off.offM - 120) < 2);
});

test("ETA: Naismith until the hiker's pace is known, then their pace", () => {
  const early = trailProgress(TRAIL, at(0), 1, { distanceM: 100, movingMs: 60_000 });
  assert.equal(early.etaBasis, "naismith");
  // 3 km and 300 m of climb: 36 + 30 minutes.
  assert.ok(Math.abs(early.etaMinutes - 66) < 1, `eta ${early.etaMinutes}`);
  const later = trailProgress(TRAIL, at(1000), 1, { distanceM: 1000, movingMs: 20 * 60_000 });
  assert.equal(later.etaBasis, "pace");
  assert.ok(Math.abs(later.etaMinutes - 40) < 0.2, `eta ${later.etaMinutes}`); // 2 km at 20 min/km
  assert.equal(gainLeft(TRAIL.profile, 3000, 1), 0);
  assert.equal(gainLeft(TRAIL.profile, 3000, -1), 0); // all downhill walking back
});

test("starting far from the trail says how far, and from what", () => {
  assert.equal(farFromTrailNote(trailLine(TRAIL), at(200, 300)), null);
  assert.equal(farFromTrailNote(trailLine(TRAIL), at(-3380)), "You're 2.1 mi from the trailhead.");
  assert.equal(farFromTrailNote(trailLine(TRAIL), at(1500, 1000)), "You're 0.6 mi from the trail.");
});

// --- saving and discarding ------------------------------------------------------------------

test("the saved body carries the track with times, and the trail", () => {
  let recording = feed(begin("trail", TRAIL), walk(60), () => 512.34);
  recording = stop(recording, T0 + 60_000);
  const body = saveBody(recording, hikeStats(recording, T0 + 60_000), "Morning");
  assert.equal(body.mode, "trail");
  assert.equal(body.osm_id, 1);
  assert.equal(body.trail_name, "Test Trail");
  assert.equal(body.elapsed_s, 60);
  const first = body.track[0][0];
  assert.deepEqual(first, [LON, LAT, 512.3, T0]);
  const times = body.track.flat().map((p) => p[3] as number);
  assert.deepEqual(times, [...times].sort((a, b) => a - b));
});

test("the hike in progress survives a reload and is cleared on save or discard", async () => {
  const kv = memoryKeyValue();
  const store = new ActiveHikeStore(kv);
  const recording = feed(begin(), walk(30));
  await store.save(recording);
  const restored = await new ActiveHikeStore(kv).load("alice");
  assert.deepEqual(restored, recording);
  await store.clear();
  assert.equal(await store.load("alice"), null);
});

test("a hike in progress is only offered back to the account that started it", async () => {
  const store = new ActiveHikeStore(memoryKeyValue());
  await store.save(feed(begin(), walk(10)));
  assert.equal(await store.load("bob"), null);
  assert.equal(await store.load(null), null);
  assert.ok(await store.load("alice"));
  // Started signed out: whoever is signed in next can save it.
  await store.save({ ...feed(begin(), walk(10)), owner: null });
  assert.ok(await store.load("bob"));
  assert.ok(await store.load(null));
});

// --- the terrain sampler's pixel arithmetic ------------------------------------------------

test("a position's DEM tile and pixel, and bilinear heights", () => {
  const { z, x, y, px, py } = tilePixel(0, 0, 1);
  assert.deepEqual([z, x, y, px, py], [1, 1, 1, 0, 0]);
  const marcy = tilePixel(-73.9859, 44.1128, 14);
  assert.deepEqual([marcy.x, marcy.y], [4824, 5950]);
  // A 2x2 tile: west 0 m, east 10 m.
  const tile = [0, 10, 0, 10];
  assert.equal(bilinear(tile, 1, 1, 2), 5);
  assert.equal(bilinear(tile, 0.5, 0.5, 2), 0);
  assert.equal(bilinear(tile, 5, 5, 2), 10); // past the edge: the edge pixel
});

// --- display, route drawing, trail snapshot ---------------------------------------------------

test("the display's clock, pace and heights", async () => {
  const { clock, pace, feetOrDash, gainFeet, defaultHikeName } = await import("../src/tracking/format.ts");
  assert.equal(clock(245_000), "0:04:05");
  assert.equal(clock(5_025_900), "1:23:45");
  assert.equal(pace(24 + 10 / 60), "24:10 /mi");
  assert.equal(pace(null), "–");
  assert.equal(feetOrDash(null), "–");
  assert.equal(feetOrDash(1000), "3,281 ft");
  assert.equal(gainFeet(100), "+328 ft");
  assert.equal(defaultHikeName("Van Hoevenberg Trail", T0), "Hike on Van Hoevenberg Trail");
});

test("a saved hike's route fits its box, north up, gaps kept", async () => {
  const { routeShape } = await import("../src/tracking/routeShape.ts");
  const track = [
    [[LON, LAT, null, T0], [LON, LAT + 0.01, null, T0 + 1]],
    [[LON + 0.01, LAT + 0.01, null, T0 + 2]], // one point: nothing to draw
    [[LON + 0.01, LAT + 0.01, null, T0 + 3], [LON + 0.01, LAT, null, T0 + 4]],
  ] as [number, number, number | null, number][][];
  const lines = routeShape(track, 200, 100);
  assert.equal(lines.length, 2);
  const [start, end] = lines[0].split(" ").map((p) => p.split(",").map(Number));
  assert.ok(start[1] > end[1], "north is up: the northern end has the smaller y");
  for (const line of lines) {
    for (const [x, y] of line.split(" ").map((p) => p.split(",").map(Number))) {
      assert.ok(x >= 0 && x <= 200 && y >= 0 && y <= 100);
    }
  }
  assert.deepEqual(routeShape([], 200, 100), []);
});

test("a trail snapshot keeps the line, profile and every place to camp along it", async () => {
  const { trailSnapshot } = await import("../src/tracking/snapshot.ts");
  const snapshot = trailSnapshot(
    {
      source_id: "relation/1",
      name: "Test Trail",
      osm_id: 1,
      assembly: null,
      line: { type: "LineString", coordinates: TRAIL.coords, length_m: 3000 },
      profile: { status: "ok", reason: null, distance_m: [0, 3000], elevation_m: [500, 800] } as never,
      campsites: {
        items: [
          { id: "node/1", name: "Lean-to", display_name: null, distance_along_m: 1000, position: "along" },
          { id: "node/2", name: "Past the end", distance_along_m: 0, position: "near_start" },
        ] as never,
      },
    },
    [{ id: "cand/1", label: "Potential spot", distance_along_m: 2500 }] as never,
  );
  assert.deepEqual(
    snapshot.stops.map((s) => [s.id, s.kind, s.alongM]),
    [
      ["node/1", "campsite", 1000],
      ["cand/1", "candidate", 2500],
    ],
  );
  assert.deepEqual(snapshot.profile, { distances: [0, 3000], elevations: [500, 800] });
  assert.equal(snapshot.fromWay, null);
});
