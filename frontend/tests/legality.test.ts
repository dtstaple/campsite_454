/**
 * TM05-76 follow-up: legality is a verdict above the score, so the breakdown under it lists
 * every factor except the legal one.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { withoutLegalFactor } from "../src/campsite/legality.ts";

const score = {
  contract: 1,
  score: 81,
  factors: [{ key: "water" }, { key: "legal" }, { key: "trail" }],
  caps: [],
};

test("the legal factor is removed and the total kept", () => {
  const out = withoutLegalFactor(score) as typeof score;
  assert.deepEqual(out.factors.map((f) => f.key), ["water", "trail"]);
  assert.equal(out.score, 81);
});

test("a JSON string from a map feature is handled too", () => {
  const out = withoutLegalFactor(JSON.stringify(score)) as typeof score;
  assert.deepEqual(out.factors.map((f) => f.key), ["water", "trail"]);
});

test("anything that is not a score is passed through for the breakdown to judge", () => {
  assert.equal(withoutLegalFactor(null), null);
  assert.equal(withoutLegalFactor("not json"), "not json");
});
