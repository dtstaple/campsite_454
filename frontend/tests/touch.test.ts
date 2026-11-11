import { test } from "node:test";
import assert from "node:assert/strict";
import { clearsOnLeave, isTouch, placeTip, tapPreview, tipFor, type TipNode } from "../src/input/touch.ts";

test("only a finger counts as touch; a mouse and a pen keep the desktop behaviour", () => {
  assert.equal(isTouch("touch"), true);
  assert.equal(isTouch("mouse"), false);
  assert.equal(isTouch("pen"), false);
  assert.equal(isTouch(""), false);
});

test("a mouse click opens straight away, as it always did", () => {
  assert.deepEqual(tapPreview(null, "a", "mouse"), { pinned: null, open: true });
  assert.deepEqual(tapPreview("b", "a", "mouse"), { pinned: "b", open: true });
});

test("a first tap previews and pins; a second tap on the same row opens it", () => {
  const first = tapPreview(null, "a", "touch");
  assert.deepEqual(first, { pinned: "a", open: false });
  assert.deepEqual(tapPreview(first.pinned, "a", "touch"), { pinned: "a", open: true });
  // Tapping another row moves the preview there instead of opening anything.
  assert.deepEqual(tapPreview("a", "b", "touch"), { pinned: "b", open: false });
});

test("the profile cursor stays where a finger left it, and goes when a mouse leaves", () => {
  assert.equal(clearsOnLeave("mouse", false), true);
  assert.equal(clearsOnLeave("mouse", true), false); // still dragging
  assert.equal(clearsOnLeave("touch", false), false);
  assert.equal(clearsOnLeave("pen", false), true);
});

const plain = (title: string | null = null): TipNode => ({ title, interactive: false, disabled: false });
const control = (title: string | null = null, disabled = false): TipNode => ({ title, interactive: true, disabled });

test("a tap on something with a title shows that title", () => {
  assert.equal(tipFor([plain("Exposed ridge, mi 1.2 to 1.6")]), 0);
  // The span tapped has none; its parent stat does.
  assert.equal(tipFor([plain(), plain("Naismith's rule, plus 1 h per 600 m up")]), 1);
  assert.equal(tipFor([plain(), plain()]), -1);
  assert.equal(tipFor([plain("   ")]), -1);
});

test("a control's tap does what the control does; only a disabled one explains itself", () => {
  assert.equal(tipFor([control("Show your location")]), -1);
  // A title inside an enabled row button: the row opens, no tip.
  assert.equal(tipFor([plain("Campsite score, 0-100"), control()]), -1);
  assert.equal(tipFor([control("You can compare up to 3 trails. Remove one first.", true)]), 0);
});

test("the tip sits centred above what was tapped, inside the screen", () => {
  const viewport = { width: 390, height: 844 };
  const tip = { width: 200, height: 40 };
  assert.deepEqual(placeTip({ left: 145, top: 400, width: 100, height: 20 }, tip, viewport), {
    left: 95,
    top: 352,
    below: false,
  });
  // Near the left edge it is pushed in, not cut off.
  assert.equal(placeTip({ left: 0, top: 400, width: 20, height: 20 }, tip, viewport).left, 8);
  // Near the right edge too.
  assert.equal(placeTip({ left: 370, top: 400, width: 20, height: 20 }, tip, viewport).left, 182);
  // No room above: it goes below.
  assert.deepEqual(placeTip({ left: 145, top: 20, width: 100, height: 20 }, tip, viewport), {
    left: 95,
    top: 48,
    below: true,
  });
});
