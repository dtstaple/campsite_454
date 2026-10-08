import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BANDS,
  bandOf,
  decodeTerrarium,
  metresPerPixel,
  parseColour,
  rowLatitude,
  slopeDegrees,
  slopeTile,
  type Rgba,
} from "../src/slope/slope.ts";

const SIZE = 64;
const PALETTE: Rgba[] = [
  [1, 1, 1, 255],
  [2, 2, 2, 255],
  [3, 3, 3, 255],
  [4, 4, 4, 255],
];

/** Encode metres as Terrarium RGB, as the AWS tiles do. */
function encode(metres: number): [number, number, number] {
  const v = metres + 32768;
  const r = Math.floor(v / 256);
  const g = Math.floor(v) % 256;
  const b = Math.floor((v - Math.floor(v)) * 256);
  return [r, g, b];
}

/** A synthetic Terrarium tile: a plane tilted `degrees` towards the east, plus `north`
 * degrees towards the north, with the real ground size of each row's pixels. */
function planeTile(z: number, y: number, degrees: number, north = 0): Uint8ClampedArray {
  const rgba = new Uint8ClampedArray(SIZE * SIZE * 4);
  for (let row = 0; row < SIZE; row++) {
    const cell = metresPerPixel(z, rowLatitude(z, y, row, SIZE), SIZE);
    for (let col = 0; col < SIZE; col++) {
      const e =
        1000 + col * cell * Math.tan((degrees * Math.PI) / 180) -
        row * cell * Math.tan((north * Math.PI) / 180);
      const [r, g, b] = encode(e);
      rgba.set([r, g, b, 255], (row * SIZE + col) * 4);
    }
  }
  return rgba;
}

/** The band every pixel of a tile landed in, as a set. */
function bandsIn(out: Uint8ClampedArray): Set<number> {
  const seen = new Set<number>();
  for (let i = 0; i < out.length; i += 4) seen.add(out[i + 3] === 0 ? 0 : out[i]);
  return seen;
}

test("Terrarium decodes as the AWS documentation gives it", () => {
  assert.equal(decodeTerrarium(128, 0, 0), 0);
  assert.equal(decodeTerrarium(132, 76, 128), 1100.5); // (132*256 + 76 + 0.5) - 32768
  const [r, g, b] = encode(1629.25);
  assert.equal(decodeTerrarium(r, g, b), 1629.25);
});

test("band edges: under 27 is none, then 27-30, 30-35, 35-45, 45+", () => {
  assert.deepEqual(
    [0, 26.9, 27, 29.9, 30, 34.9, 35, 44.9, 45, 70].map(bandOf),
    [0, 0, 1, 1, 2, 2, 3, 3, 4, 4],
  );
  assert.deepEqual(BANDS.map((b) => b.label), ["27–30°", "30–35°", "35–45°", "45° and over"]);
});

test("a plane's slope is recovered exactly, edges included", () => {
  const cell = 10;
  const elevation = new Float32Array(SIZE * SIZE);
  const tan = Math.tan((33 * Math.PI) / 180);
  for (let row = 0; row < SIZE; row++)
    for (let col = 0; col < SIZE; col++) elevation[row * SIZE + col] = col * cell * tan;
  const slopes = slopeDegrees(elevation, SIZE, () => cell);
  for (const value of slopes) assert.ok(Math.abs(value - 33) < 1e-3, `got ${value}`);
});

test("a slope facing any direction measures the same", () => {
  const cell = 10;
  const elevation = new Float32Array(SIZE * SIZE);
  // 40 degrees, facing south-west: the gradient split between both axes.
  const g = Math.tan((40 * Math.PI) / 180) / Math.SQRT2;
  for (let row = 0; row < SIZE; row++)
    for (let col = 0; col < SIZE; col++)
      elevation[row * SIZE + col] = (col + row) * cell * g;
  const slopes = slopeDegrees(elevation, SIZE, () => cell);
  for (const value of slopes) assert.ok(Math.abs(value - 40) < 1e-3, `got ${value}`);
});

test("known test tiles land in the expected bands (Adirondack latitude, zoom 14)", () => {
  // Tile y for 44.1N at zoom 14 (Lake Placid).
  const z = 14;
  const y = 5951;
  assert.ok(Math.abs(rowLatitude(z, y, SIZE / 2, SIZE) - 44.1) < 0.1);
  const cases: [number, number][] = [
    [10, 0],
    [28.5, 1],
    [32.5, 2],
    [40, 3],
    [52, 4],
  ];
  for (const [degrees, band] of cases) {
    const out = slopeTile(planeTile(z, y, degrees), z, y, PALETTE, SIZE);
    assert.deepEqual([...bandsIn(out)], [band], `${degrees}°`);
  }
});

test("a tile with flat ground beside a cliff shades only the cliff", () => {
  const z = 14;
  const y = 5951;
  const rgba = new Uint8ClampedArray(SIZE * SIZE * 4);
  for (let row = 0; row < SIZE; row++)
    for (let col = 0; col < SIZE; col++) {
      // Flat at 500 m for the left half; a 60 degree wall for the right.
      const cell = metresPerPixel(z, rowLatitude(z, y, row, SIZE), SIZE);
      const e = col < SIZE / 2 ? 500 : 500 + (col - SIZE / 2) * cell * Math.tan(Math.PI / 3);
      rgba.set([...encode(e), 255], (row * SIZE + col) * 4);
    }
  const out = slopeTile(rgba, z, y, PALETTE, SIZE);
  const bandAt = (col: number) => (out[(10 * SIZE + col) * 4 + 3] ? out[(10 * SIZE + col) * 4] : 0);
  assert.equal(bandAt(5), 0); // flat
  assert.equal(bandAt(SIZE - 5), 4); // the wall: 45+
});

test("ignoring latitude would misjudge slopes, so it is not ignored", () => {
  // At 44N a Web Mercator pixel covers cos(44) of its equatorial width.
  assert.ok(Math.abs(metresPerPixel(14, 44.1) / metresPerPixel(14, 0) - Math.cos((44.1 * Math.PI) / 180)) < 1e-9);
  assert.ok(Math.abs(metresPerPixel(14, 44.1) - 6.87) < 0.01);
});

test("theme colours parse as hex and rgba", () => {
  assert.deepEqual(parseColour("#f2e14c"), [242, 225, 76, 255]);
  assert.deepEqual(parseColour(" rgba(229, 65, 45, 0.5) "), [229, 65, 45, 128]);
  assert.deepEqual(parseColour("nonsense"), [0, 0, 0, 255]);
});

test("smoothing leaves a plane's slope exactly as it was", async () => {
  const { smoothElevation } = await import("../src/slope/slope.ts");
  const cell = 10;
  const elevation = new Float32Array(SIZE * SIZE);
  const tan = Math.tan((37 * Math.PI) / 180);
  for (let row = 0; row < SIZE; row++)
    for (let col = 0; col < SIZE; col++) elevation[row * SIZE + col] = (col * 0.6 + row * 0.8) * cell * tan;
  const slopes = slopeDegrees(smoothElevation(elevation, SIZE), SIZE, () => cell);
  for (const value of slopes) assert.ok(Math.abs(value - 37) < 0.01, `got ${value}`);
});

test("smoothing removes a one-pixel terrace from flat ground", async () => {
  const { smoothElevation } = await import("../src/slope/slope.ts");
  const cell = 7;
  const elevation = new Float32Array(SIZE * SIZE).fill(500);
  // An 8 m step one pixel wide: the raw 3x3 slope puts flat ground in the 27-30 band.
  for (let row = 0; row < SIZE; row++)
    for (let col = SIZE / 2; col < SIZE; col++) elevation[row * SIZE + col] = 508;
  const raw = slopeDegrees(elevation, SIZE, () => cell);
  const smoothed = slopeDegrees(smoothElevation(elevation, SIZE), SIZE, () => cell);
  const mid = 10 * SIZE + SIZE / 2;
  assert.equal(bandOf(raw[mid]), 1, `raw ${raw[mid]}`);
  assert.equal(bandOf(smoothed[mid]), 0, `smoothed ${smoothed[mid]}`);
});
