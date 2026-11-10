/** TM05-134: the app follows the visible screen, sheets adapt to a short map, no overscroll. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { SHORT_AVAILABLE_PX, SHORT_MAP_KEPT, snapHeights } from "../src/components/snaps.ts";

const SRC = join(import.meta.dirname, "..", "src");
const css = (file: string) =>
  readFileSync(join(SRC, file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function rule(source: string, selector: string): string {
  const start = source.indexOf(`${selector} {`);
  assert.ok(start >= 0, `no ${selector} rule`);
  return source.slice(start, source.indexOf("}", start));
}

test("the app root is 100dvh, after a 100vh fallback", () => {
  const shell = rule(css("App.css"), ".shell");
  const vh = shell.indexOf("height: 100vh;");
  const dvh = shell.indexOf("height: 100dvh;");
  assert.ok(vh >= 0 && dvh > vh, "100vh must come first, so 100dvh wins where it is supported");
});

test("the map page has overscroll-behavior: none, on the page and the app", () => {
  const app = css("App.css");
  const block = app.slice(app.indexOf("html:has(.app)"));
  assert.match(block.slice(0, block.indexOf("}")), /^html:has\(\.app\),\s*html:has\(\.app\) body,\s*\.app \{\s*overscroll-behavior: none;/);
});

test("a phone in landscape (~390 px tall) keeps a usable map at every snap", () => {
  // 390 px of screen, less the slim header and Safari's bars: about 320 px of map.
  for (const available of [260, 320, 360, SHORT_AVAILABLE_PX]) {
    const heights = snapHeights(available);
    const kept = available - heights.full;
    assert.ok(kept >= Math.round(available * SHORT_MAP_KEPT), `${available}: full leaves ${kept}px`);
    assert.ok(heights.peek <= available * 0.3 + 1, `${available}: peek ${heights.peek}px`);
    assert.ok(heights.peek <= heights.half && heights.half <= heights.full, `${available}: order`);
  }
  assert.deepEqual(snapHeights(320), { peek: 96, half: 160, full: 192 });
});

test("the snaps follow the height as the browser bars show and hide", () => {
  const barsShown = snapHeights(320);
  const barsHidden = snapHeights(372);
  assert.ok(barsHidden.full > barsShown.full && barsHidden.half > barsShown.half);
});

test("a tall phone map keeps the original sizes", () => {
  assert.deepEqual(snapHeights(760), { peek: 132, half: 380, full: 704 });
  assert.deepEqual(snapHeights(SHORT_AVAILABLE_PX + 1), { peek: 132, half: 251, full: 445 });
});

test("the trip plan table can shrink to a 375 px sheet", () => {
  const plans = css("plans/plans.css");
  assert.match(rule(plans, ".plan-days td:nth-child(2)"), /overflow-wrap: anywhere;/);
  const phone = plans.slice(plans.indexOf("@media (max-width: 640px)"));
  assert.match(phone, /\.plan-days \{\s*font-size: var\(--text-xs\);/);
});
