import { test } from "node:test";
import assert from "node:assert/strict";
import { gpxPath } from "../src/trails/gpx.ts";

test("a route relation exports through its own endpoint", () => {
  assert.equal(gpxPath({ osm_id: 1376439 }, 500), "/api/routes/1376439/gpx/?campsites_within_m=500");
});

test("an assembled trail exports through the way it was opened from", () => {
  assert.equal(
    gpxPath({ osm_id: null, assembly: { from_way: "way/20074658" } }, 1000),
    "/api/trails/way/20074658/gpx/?campsites_within_m=1000",
  );
});

test("no relation and no way: nothing to download", () => {
  assert.equal(gpxPath({ osm_id: null, assembly: null }, 500), null);
});

test("the saved file name matches the API's", async () => {
  const { gpxFilename } = await import("../src/trails/gpx.ts");
  assert.equal(gpxFilename("Van Hoevenberg Trail"), "van-hoevenberg-trail.gpx");
  assert.equal(gpxFilename("../../etc/passwd"), "etc-passwd.gpx");
  assert.equal(gpxFilename(""), "trail.gpx");
});
