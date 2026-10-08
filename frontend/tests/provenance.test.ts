/**
 * TM05-77: the panel's provenance line under the confidence level.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { provenance } from "../src/campsite/format.ts";

test("source and the date of the last ingest", () => {
  assert.equal(
    provenance("Recreation.gov (RIDB)", "2026-09-19T12:05:00+00:00"),
    "Recreation.gov (RIDB) · updated Sep 19, 2026",
  );
});

test("no date, or an unreadable one, shows the source alone", () => {
  assert.equal(provenance("OpenStreetMap", null), "OpenStreetMap");
  assert.equal(provenance("OpenStreetMap", "not a date"), "OpenStreetMap");
});
