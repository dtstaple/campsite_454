/**
 * Slope-angle bands from a Terrarium DEM tile (TM05-84). Pure -- arrays in, arrays out --
 * so node --test checks it on synthetic tiles with known slopes, and the web worker
 * (slope.worker.ts) runs exactly this code.
 *
 *   1. Decode Terrarium: elevation_m = R * 256 + G + B / 256 - 32768.
 *   2. Slope per pixel by Horn's method (the 3x3 finite difference GDAL's gdaldem and
 *      ArcGIS use), with the ground size of a pixel taken at that pixel's own latitude
 *      (Web Mercator stretches it by 1 / cos(latitude)).
 *   3. Band it: under 27°, 27-30°, 30-35°, 35-45°, 45° and over.
 *
 * Before step 2 the elevations get a light smoothing (smoothElevation), which removes the
 * tiles' quantisation terraces without changing any true slope.
 *
 * At a tile's edge the missing neighbours are replaced by one-sided differences rather
 * than by repeating the edge pixel, which would halve the gradient there and draw a
 * light seam along every tile boundary.
 */

export const TILE_SIZE = 256;
const EARTH_CIRCUMFERENCE_M = 40_075_016.686;

/** Band edges in degrees: a pixel is in band i when EDGES[i-1] <= slope < EDGES[i]. */
export const BAND_EDGES = [27, 30, 35, 45] as const;
/** Band 0 is "under 27°" and is left transparent. */
export const BANDS = [
  { band: 1, label: "27–30°", token: "--slope-27" },
  { band: 2, label: "30–35°", token: "--slope-30" },
  { band: 3, label: "35–45°", token: "--slope-35" },
  { band: 4, label: "45° and over", token: "--slope-45" },
] as const;

export function decodeTerrarium(r: number, g: number, b: number): number {
  return r * 256 + g + b / 256 - 32768;
}

/** Elevations (m) from RGBA pixel data, row-major. */
export function decodeTile(rgba: Uint8ClampedArray | Uint8Array, size = TILE_SIZE): Float32Array {
  const out = new Float32Array(size * size);
  for (let i = 0; i < size * size; i++) {
    out[i] = decodeTerrarium(rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2]);
  }
  return out;
}

/**
 * Terrarium tiles are resampled and quantised, which leaves faint terraces: steps a pixel
 * or two wide that a 3x3 slope reads as steep. A 3x3 mean, applied SMOOTH_PASSES times,
 * removes them. A mean leaves a plane exactly as it is, so true slopes are unchanged; the
 * outer ring of pixels is left as it was, so the result never depends on a shrunken
 * window at the tile edge.
 */
export const SMOOTH_PASSES = 2;

export function smoothElevation(elevation: Float32Array, size: number, passes = SMOOTH_PASSES) {
  let current = elevation;
  for (let pass = 0; pass < passes; pass++) {
    const next = new Float32Array(current);
    for (let row = 1; row < size - 1; row++) {
      for (let col = 1; col < size - 1; col++) {
        let sum = 0;
        for (let dr = -1; dr <= 1; dr++)
          for (let dc = -1; dc <= 1; dc++) sum += current[(row + dr) * size + col + dc];
        next[row * size + col] = sum / 9;
      }
    }
    current = next;
  }
  return current;
}

/** Latitude (degrees) of a pixel row's centre in Web Mercator tile z/y. */
export function rowLatitude(z: number, y: number, row: number, size = TILE_SIZE): number {
  const n = Math.PI - (2 * Math.PI * (y + (row + 0.5) / size)) / 2 ** z;
  return (180 / Math.PI) * Math.atan(Math.sinh(n));
}

/** Ground metres per pixel at a latitude and zoom. */
export function metresPerPixel(z: number, latitude: number, size = TILE_SIZE): number {
  return (EARTH_CIRCUMFERENCE_M * Math.cos((latitude * Math.PI) / 180)) / (size * 2 ** z);
}

/**
 * Slope in degrees for every pixel. `pixelMetres(row)` is the ground size of a pixel on
 * that row (the same east-west and north-south in Web Mercator).
 */
export function slopeDegrees(
  elevation: Float32Array,
  size: number,
  pixelMetres: (row: number) => number,
): Float32Array {
  const out = new Float32Array(size * size);
  const at = (col: number, row: number) => elevation[row * size + col];
  for (let row = 0; row < size; row++) {
    const cell = pixelMetres(row);
    // Neighbour rows/cols, or the pixel itself at an edge (one-sided difference).
    const up = row > 0 ? row - 1 : row;
    const down = row < size - 1 ? row + 1 : row;
    const rowSpan = down - up; // 2 inside, 1 at an edge
    for (let col = 0; col < size; col++) {
      const left = col > 0 ? col - 1 : col;
      const right = col < size - 1 ? col + 1 : col;
      const colSpan = right - left;
      // Horn: weighted differences across the 3x3 window.
      const dzdx =
        (at(right, up) + 2 * at(right, row) + at(right, down) -
          (at(left, up) + 2 * at(left, row) + at(left, down))) /
        (4 * colSpan * cell);
      const dzdy =
        (at(left, down) + 2 * at(col, down) + at(right, down) -
          (at(left, up) + 2 * at(col, up) + at(right, up))) /
        (4 * rowSpan * cell);
      out[row * size + col] = (Math.atan(Math.hypot(dzdx, dzdy)) * 180) / Math.PI;
    }
  }
  return out;
}

/** 0 for under 27°, then 1-4 for the bands. */
export function bandOf(degrees: number): number {
  let band = 0;
  for (const edge of BAND_EDGES) if (degrees >= edge) band++;
  return band;
}

export type Rgba = [number, number, number, number];

/** RGBA pixels: each band's colour, transparent below the first band. */
export function colourBands(
  slopes: Float32Array,
  palette: readonly Rgba[],
): Uint8ClampedArray<ArrayBuffer> {
  const out = new Uint8ClampedArray(new ArrayBuffer(slopes.length * 4));
  for (let i = 0; i < slopes.length; i++) {
    const band = bandOf(slopes[i]);
    if (band === 0) continue;
    const [r, g, b, a] = palette[band - 1];
    out[i * 4] = r;
    out[i * 4 + 1] = g;
    out[i * 4 + 2] = b;
    out[i * 4 + 3] = a;
  }
  return out;
}

/** The whole tile: Terrarium RGBA in, banded RGBA out. */
export function slopeTile(
  rgba: Uint8ClampedArray | Uint8Array,
  z: number,
  y: number,
  palette: readonly Rgba[],
  size = TILE_SIZE,
): Uint8ClampedArray<ArrayBuffer> {
  const elevation = smoothElevation(decodeTile(rgba, size), size);
  const slopes = slopeDegrees(elevation, size, (row) =>
    metresPerPixel(z, rowLatitude(z, y, row, size), size),
  );
  return colourBands(slopes, palette);
}

/** "#f2e14c" or "rgb(242, 225, 76)" -> [242, 225, 76, 255]. Black if unreadable. */
export function parseColour(value: string): Rgba {
  const text = value.trim();
  const hex = /^#([0-9a-f]{6})$/i.exec(text);
  if (hex) {
    const n = Number.parseInt(hex[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 255];
  }
  const rgb = /^rgba?\(([^)]+)\)$/i.exec(text);
  if (rgb) {
    const [r, g, b, a = "1"] = rgb[1].split(",").map((part) => part.trim());
    return [Number(r), Number(g), Number(b), Math.round(Number(a) * 255)];
  }
  return [0, 0, 0, 255];
}
