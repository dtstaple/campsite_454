import { test } from "node:test";
import assert from "node:assert/strict";
import { autoBody, consideredLine, reasonsByStop, sameStops } from "../src/plans/auto.ts";

test("nights must be a whole number above zero", () => {
  assert.deepEqual(autoBody("nights", "3"), { nights: 3 });
  assert.deepEqual(autoBody("nights", " 2 "), { nights: 2 });
  assert.deepEqual(autoBody("nights", "2.5"), { error: "Enter a whole number of nights." });
  assert.deepEqual(autoBody("nights", "0"), { error: "Enter a number of nights." });
  assert.deepEqual(autoBody("nights", ""), { error: "Enter a number of nights." });
  assert.deepEqual(autoBody("nights", "two"), { error: "Enter a number of nights." });
});

test("a daily target in miles is sent in metres", () => {
  assert.deepEqual(autoBody("miles", "10"), { daily_target_m: 16093 });
  assert.deepEqual(autoBody("miles", "7.5"), { daily_target_m: 12070 });
  assert.deepEqual(autoBody("miles", "-1"), { error: "Enter miles a day." });
});

test("the reasons apply only while the draft has exactly the auto-plan's stops", () => {
  assert.equal(sameStops(["a", "b"], ["b", "a"]), true);
  assert.equal(sameStops(["a", "b"], ["a"]), false);
  assert.equal(sameStops(["a", "b"], ["a", "c"]), false);
  assert.equal(sameStops([], []), true);
});

test("reasons are found by stop id", () => {
  const reasons = reasonsByStop({
    choices: [
      { night: 1, id: "node/1", reason: "Score 91: the only legal stop." },
    ] as never,
  });
  assert.equal(reasons.get("node/1"), "Score 91: the only legal stop.");
  assert.equal(reasons.get("node/2"), undefined);
});

test("the summary says what was considered and that potential spots are never chosen", () => {
  const considered = {
    within_m: 500,
    mapped: 61,
    mapped_permitted: 52,
    mapped_truncated: false,
    candidates_searched: false,
    candidates: null,
  };
  assert.equal(
    consideredLine({ considered, nights_planned: 3 }),
    "Auto-planned 3 nights from 52 legal of 61 mapped campsites. Only Permitted stops are " +
      "chosen: potential spots are unverified, so they are never chosen automatically " +
      "(Find campsites hasn't been run here).",
  );
  assert.match(
    consideredLine({ considered: { ...considered, candidates_searched: true, candidates: 5 }, nights_planned: 1 }),
    /^Auto-planned 1 night from .*\(Find campsites found 5\)\.$/,
  );
});
