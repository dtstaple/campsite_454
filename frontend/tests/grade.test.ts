/**
 * TM05-48: the score colour system. The map paint, legend and panel all read GRADES, so
 * these pin the bands and, above all, that "no score" never becomes an F.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  bandLabel,
  GRADES,
  gradeFor,
  gradeToken,
  scoreColorExpression,
  type ScoreColors,
} from "../src/score/grade.ts";

const colors: ScoreColors = { A: "a", B: "b", C: "c", D: "d", F: "f", none: "none" };

test("band edges land on the higher grade", () => {
  assert.equal(gradeFor(100), "A");
  assert.equal(gradeFor(90), "A");
  assert.equal(gradeFor(89), "B");
  assert.equal(gradeFor(80), "B");
  assert.equal(gradeFor(70), "C");
  assert.equal(gradeFor(60), "D");
  assert.equal(gradeFor(59), "F");
});

test("0 is a real score -- closed land is capped to it -- and is an F", () => {
  assert.equal(gradeFor(0), "F");
});

test("anything that is not a number is no score, not an F", () => {
  for (const value of [null, undefined, "81", Number.NaN, {}]) {
    assert.equal(gradeFor(value), null, String(value));
  }
});

test("each grade and no-score have their own theme token", () => {
  const tokens = [...GRADES.map((grade) => gradeToken(grade.letter)), gradeToken(null)];
  assert.deepEqual(tokens, [
    "--score-a",
    "--score-b",
    "--score-c",
    "--score-d",
    "--score-f",
    "--score-none",
  ]);
});

test("legend labels follow the bands", () => {
  assert.deepEqual(
    GRADES.map((grade) => bandLabel(grade.letter)),
    ["A 90+", "B 80+", "C 70+", "D 60+", "F < 60"],
  );
});

test("the map expression steps through the same bands, neutral for no score", () => {
  assert.deepEqual(scoreColorExpression(colors), [
    "case",
    ["==", ["typeof", ["get", "score"]], "number"],
    ["step", ["get", "score"], "f", 60, "d", 70, "c", 80, "b", 90, "a"],
    "none",
  ]);
});

/** Evaluate the expression the way MapLibre would, for one feature's `score`. */
function paint(score: unknown): string {
  const expression = scoreColorExpression(colors);
  const fallback = expression[3] as string;
  // MapLibre's typeof says "null" for null and for a missing property.
  if (typeof score !== "number") return fallback;
  const [, , ...steps] = expression[2] as unknown[]; // ["step", input, f, 60, d, ...]
  let colour = steps[0] as string;
  for (let i = 1; i < steps.length; i += 2) {
    if (score >= (steps[i] as number)) colour = steps[i + 1] as string;
  }
  return colour;
}

test("the expression and gradeFor agree on every score", () => {
  for (let score = 0; score <= 100; score += 1) {
    assert.equal(paint(score), gradeFor(score)!.toLowerCase(), `score ${score}`);
  }
  assert.equal(paint(undefined), "none");
  assert.equal(paint(null), "none");
});
