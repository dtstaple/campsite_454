import { test } from "node:test";
import assert from "node:assert/strict";
import { KINDS, defaultName, draftError, kindStyle } from "../src/waypoints/kinds.ts";

test("the four kinds match the server's, each with its own colour and glyph", () => {
  assert.deepEqual(KINDS.map((k) => k.id), ["water", "camp", "bailout", "custom"]);
  assert.equal(new Set(KINDS.map((k) => k.token)).size, 4);
  assert.equal(new Set(KINDS.map((k) => k.glyph)).size, 4);
});

test("an unknown kind draws as custom", () => {
  assert.equal(kindStyle("helipad").id, "custom");
});

test("drafts need a name and bounded text", () => {
  assert.equal(draftError({ name: "  ", note: "" }), "Give the waypoint a name.");
  assert.match(draftError({ name: "x".repeat(81), note: "" }) ?? "", /under 80/);
  assert.match(draftError({ name: "Spring", note: "n".repeat(2001) }) ?? "", /under 2000/);
  assert.equal(draftError({ name: "Spring", note: "" }), null);
});

test("default names count up past the ones already taken", () => {
  assert.equal(defaultName("water", []), "Water");
  assert.equal(defaultName("water", [{ name: "Water" }, { name: "Water 2" }]), "Water 3");
  assert.equal(defaultName("bailout", [{ name: "Water" }]), "Bail-out");
});
