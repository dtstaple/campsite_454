import { test } from "node:test";
import assert from "node:assert/strict";
import {
  errorMessage,
  fetchPointViewshed,
  LONG_PRESS_MOVE_PX,
  LONG_PRESS_MS,
  LongPress,
  MENU_LABEL,
  placeLabel,
  viewshedUrl,
  ViewshedError,
} from "../src/viewshed/here.ts";

const FEATURE = {
  type: "Feature",
  geometry: { type: "MultiPolygon", coordinates: [] },
  properties: {
    observer: { lat: 44.15025, lon: -73.95025 },
    region: "adirondacks",
    radius_m: 10000,
    eye_height_m: 1.7,
    resolution_m: 30,
    area_km2: 7.1,
    direction: "east",
    summary: "About 7.1 km² visible within 10 km, mostly to the east.",
    label: "Bare-earth elevation",
    note: "Terrain-model estimate from bare-earth elevation. Trees, buildings and recent changes aren't counted.",
    cached: false,
    computed_at: "2026-11-02T23:00:00Z",
  },
};

function respond(status: number, body: unknown) {
  return async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

test("the menu offers the one question", () => {
  assert.equal(MENU_LABEL, "What can I see from here?");
});

test("the request names the point", () => {
  assert.equal(viewshedUrl("http://api", 44.1502, -73.9502), "http://api/api/viewshed/?lat=44.150200&lon=-73.950200");
  assert.equal(placeLabel(44.1502, -73.9502), "44.15020, -73.95020");
});

test("a viewshed arrives labelled bare-earth elevation, with the caveat", async (t) => {
  t.mock.method(globalThis, "fetch", respond(200, FEATURE));
  const feature = await fetchPointViewshed("http://api", 44.15, -73.95);
  assert.equal(feature.properties.label, "Bare-earth elevation");
  assert.match(feature.properties.note, /Trees, buildings/);
  assert.match(feature.properties.summary, /km² visible/);
});

test("errors say what went wrong, using the server's reason", async (t) => {
  t.mock.method(globalThis, "fetch", respond(503, { error: "The terrain model hasn't been built for adirondacks yet." }));
  await assert.rejects(fetchPointViewshed("http://api", 44.15, -73.95), (error: unknown) => {
    assert.ok(error instanceof ViewshedError);
    assert.match(error.message, /^Can't work out the view here right now\. The terrain model/);
    return true;
  });
  assert.equal(
    errorMessage(422, { error: "That point is outside the areas CampSite covers." }),
    "That point is outside the areas CampSite covers.",
  );
  assert.match(errorMessage(500, null), /HTTP 500/);
  assert.match(errorMessage(503, "oops"), /terrain model isn't available/);
});

test("a network failure is a friendly error", async (t) => {
  t.mock.method(globalThis, "fetch", async () => {
    throw new TypeError("Failed to fetch");
  });
  await assert.rejects(fetchPointViewshed("http://api", 44.15, -73.95), /Couldn't reach the server/);
});

test("a long press fires once, after the hold time", () => {
  const press = new LongPress();
  press.start(100, 100, 0);
  assert.equal(press.due(LONG_PRESS_MS - 1), false);
  assert.equal(press.due(LONG_PRESS_MS), true);
  assert.equal(press.due(LONG_PRESS_MS + 100), false);
});

test("drifting, a second finger or lifting early cancels it", () => {
  const drift = new LongPress();
  drift.start(100, 100, 0);
  drift.move(100 + LONG_PRESS_MOVE_PX + 1, 100);
  assert.equal(drift.due(LONG_PRESS_MS), false);

  const wobble = new LongPress();
  wobble.start(100, 100, 0);
  wobble.move(100 + LONG_PRESS_MOVE_PX - 2, 100);
  assert.equal(wobble.due(LONG_PRESS_MS), true);

  const pinch = new LongPress();
  pinch.start(100, 100, 0, 2);
  assert.equal(pinch.due(LONG_PRESS_MS), false);

  const lifted = new LongPress();
  lifted.start(100, 100, 0);
  lifted.cancel();
  assert.equal(lifted.due(LONG_PRESS_MS), false);
});
