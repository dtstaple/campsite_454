import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { BREAKPOINTS, MEDIA, layoutFor } from "../src/layout/breakpoints.ts";

const SRC = join(import.meta.dirname, "..", "src");

function filesUnder(dir: string, pattern: RegExp): string[] {
  return readdirSync(dir, { withFileTypes: true, recursive: true })
    .filter((entry) => entry.isFile() && pattern.test(entry.name))
    .map((entry) => join(entry.parentPath, entry.name));
}

test("the widths the AC names get the layouts they should", () => {
  assert.equal(layoutFor(320), "phone");
  assert.equal(layoutFor(390), "phone");
  assert.equal(layoutFor(640), "phone");
  assert.equal(layoutFor(641), "tablet");
  assert.equal(layoutFor(768), "tablet"); // iPad portrait
  assert.equal(layoutFor(844), "tablet"); // iPhone 14 in landscape
  assert.equal(layoutFor(932), "tablet"); // iPhone Pro Max in landscape
  assert.equal(layoutFor(1024), "tablet"); // iPad landscape
  assert.equal(layoutFor(1279), "tablet");
  assert.equal(layoutFor(1280), "desktop");
  assert.equal(layoutFor(1440), "desktop");
});

test("the media queries agree with the numbers they are built from", () => {
  assert.equal(MEDIA.phone, "(max-width: 640px)");
  assert.equal(MEDIA.tablet, "(min-width: 641px) and (max-width: 1279px)");
  assert.equal(MEDIA.belowDesktop, "(max-width: 1279px)");
  assert.ok(BREAKPOINTS.phoneMaxPx < BREAKPOINTS.tabletMaxPx);
});

test("every @media width in a stylesheet is one of the shared queries", () => {
  const allowed = new Set<string>(Object.values(MEDIA));
  const strays: string[] = [];
  for (const file of filesUnder(SRC, /\.css$/)) {
    const css = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const match of css.matchAll(/@media\s+([^{]+)\{/g)) {
      const query = match[1].trim().replace(/\s+/g, " ");
      if (!/\bwidth\b/.test(query)) continue; // pointer, hover, reduced motion
      if (!allowed.has(query)) strays.push(`${file.slice(SRC.length + 1)}: @media ${query}`);
    }
  }
  assert.deepEqual(strays, [], "use a query from src/layout/breakpoints.ts MEDIA");
});

test("no component spells out its own width query", () => {
  const strays: string[] = [];
  for (const file of filesUnder(SRC, /\.tsx?$/)) {
    if (file.endsWith(join("layout", "breakpoints.ts"))) continue;
    const code = readFileSync(file, "utf8");
    for (const match of code.matchAll(/matchMedia\(\s*["'`]([^"'`]*width[^"'`]*)["'`]/g)) {
      strays.push(`${file.slice(SRC.length + 1)}: ${match[1]}`);
    }
    if (/\binnerWidth\b/.test(code)) strays.push(`${file.slice(SRC.length + 1)}: innerWidth`);
  }
  assert.deepEqual(strays, [], "import MEDIA from src/layout/breakpoints.ts");
});
