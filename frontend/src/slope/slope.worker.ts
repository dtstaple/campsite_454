/**
 * Slope tiles off the main thread (TM05-84). Receives a DEM tile URL and its z/y, fetches
 * the Terrarium PNG, and answers with a PNG of the slope bands. All the maths is slope.ts.
 */

import { slopeTile, type Rgba } from "./slope";

interface Request {
  id: number;
  url: string;
  z: number;
  y: number;
  palette: Rgba[];
}

self.onmessage = async (event: MessageEvent<Request>) => {
  const { id, url, z, y, palette } = event.data;
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`DEM tile answered ${response.status}`);
    // No colour management or premultiplying: the pixels are elevations, not colours, and
    // either would change them.
    const bitmap = await createImageBitmap(await response.blob(), {
      colorSpaceConversion: "none",
      premultiplyAlpha: "none",
    });
    const { width, height } = bitmap;
    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("No 2D canvas in this worker");
    context.drawImage(bitmap, 0, 0);
    bitmap.close();
    const pixels = context.getImageData(0, 0, width, height).data;
    const banded = slopeTile(pixels, z, y, palette, width);
    context.clearRect(0, 0, width, height);
    context.putImageData(new ImageData(banded, width, height), 0, 0);
    const buffer = await (await canvas.convertToBlob({ type: "image/png" })).arrayBuffer();
    (self as unknown as Worker).postMessage({ id, buffer }, [buffer]);
  } catch (error) {
    (self as unknown as Worker).postMessage({ id, error: String(error) });
  }
};
