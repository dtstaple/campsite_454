/**
 * The font map labels are set in. Shared by the contour labels (TM05-83) and the peak and
 * trailhead labels (TM05-122).
 */

import type * as maplibregl from "maplibre-gl";

/** A font the style's glyph server has: the first one its own labels use. */
export function labelFont(map: maplibregl.Map): string[] {
  for (const layer of map.getStyle().layers ?? []) {
    if (layer.type !== "symbol") continue;
    const font = layer.layout?.["text-font"];
    if (Array.isArray(font) && font.every((f) => typeof f === "string")) return font as string[];
  }
  return ["Stadia Regular"];
}
