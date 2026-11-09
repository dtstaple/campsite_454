import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  KEYBOARD_MIN_PX,
  REVEAL_MARGIN_PX,
  isTextEntry,
  keyboardInset,
  revealDelta,
} from "../src/components/keyboard.ts";

test("the keyboard covers what the visual viewport no longer shows", () => {
  // Android Chrome: an 844 px layout, the keyboard leaves 508 px visible at the top.
  assert.equal(keyboardInset(844, { height: 508, offsetTop: 0 }), 336);
  // iOS Safari pans the layout too: 300 px panned plus 400 px visible leaves 144 covered.
  assert.equal(keyboardInset(844, { height: 400, offsetTop: 300 }), 144);
});

test("no keyboard: closed, a browser toolbar moving, or no visual viewport", () => {
  assert.equal(keyboardInset(844, { height: 844, offsetTop: 0 }), 0);
  assert.equal(keyboardInset(844, { height: 844 - 56, offsetTop: 0 }), 0); // toolbar
  assert.equal(keyboardInset(844, { height: 844 - KEYBOARD_MIN_PX + 1, offsetTop: 0 }), 0);
  assert.equal(keyboardInset(844, { height: 844 - KEYBOARD_MIN_PX, offsetTop: 0 }), KEYBOARD_MIN_PX);
  assert.equal(keyboardInset(844, null), 0);
  // Pinch-zoomed in, the visible part can be panned past the layout; never negative.
  assert.equal(keyboardInset(844, { height: 300, offsetTop: 600 }), 0);
});

test("text fields bring up the keyboard; checkboxes, buttons and read-only fields don't", () => {
  for (const type of ["text", "search", "email", "number", "tel", "url", "password", ""]) {
    assert.equal(isTextEntry({ tagName: "INPUT", type }), true, type);
  }
  assert.equal(isTextEntry({ tagName: "TEXTAREA" }), true);
  assert.equal(isTextEntry({ tagName: "DIV", isContentEditable: true }), true);
  for (const type of ["checkbox", "radio", "range", "submit", "button", "file", "color"]) {
    assert.equal(isTextEntry({ tagName: "INPUT", type }), false, type);
  }
  assert.equal(isTextEntry({ tagName: "INPUT", type: "text", readOnly: true }), false);
  assert.equal(isTextEntry({ tagName: "BUTTON" }), false);
  assert.equal(isTextEntry(null), false);
});

test("a field under the keyboard scrolls up just far enough, with a margin", () => {
  const visible = { top: 0, bottom: 500 };
  // The waypoint note at 560-620 px, behind a keyboard that starts at 500 px.
  assert.equal(revealDelta({ top: 560, bottom: 620 }, visible), 620 - 500 + REVEAL_MARGIN_PX);
  // Already in view: no scroll at all.
  assert.equal(revealDelta({ top: 100, bottom: 140 }, visible), 0);
  // Scrolled off the top: scroll back down to it.
  assert.equal(revealDelta({ top: -40, bottom: 0 }, visible), -40 - REVEAL_MARGIN_PX);
});

test("a field taller than the visible part is aligned by its top, where typing starts", () => {
  const delta = revealDelta({ top: 300, bottom: 900 }, { top: 0, bottom: 400 });
  assert.equal(delta, 300 - REVEAL_MARGIN_PX);
});

test("no text field on a touch screen is small enough for iOS to zoom into", () => {
  const theme = readFileSync(new URL("../src/theme.css", import.meta.url), "utf8");
  const size = Number(/--text-input-touch:\s*(\d+)px/.exec(theme)?.[1]);
  assert.ok(size >= 16, `--text-input-touch is ${size}px`);
  const phone = readFileSync(new URL("../src/phone.css", import.meta.url), "utf8");
  const coarse = phone.slice(phone.indexOf("@media (pointer: coarse)"));
  assert.match(coarse, /textarea[\s\S]*font-size:\s*var\(--text-input-touch\)/);
});
