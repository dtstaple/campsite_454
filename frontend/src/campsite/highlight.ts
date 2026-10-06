/**
 * Paint for the selected and hovered campsite circle (TM05-69).
 *
 * Driven by state, not by re-adding layers:
 *   - feature-state `selected` / `hover` on the "campsites" source, keyed by source_id
 *     (layers.ts promotes `source_id` to the feature id for exactly this);
 *   - global state SELECTED_STATE, true while any campsite is selected, which dims the
 *     rest.
 * SelectedCampsite.tsx sets both. layers.ts wraps the campsite layer's existing values
 * with these, so with nothing selected the map paints exactly as before.
 */

import type * as maplibregl from "maplibre-gl";
import { numericToken, token } from "../theme";

export const SELECTED_STATE = "campsiteSelected";

type Value = number | string | maplibregl.ExpressionSpecification;
type Expression = maplibregl.ExpressionSpecification;

const selected: Expression = ["boolean", ["feature-state", "selected"], false];
const hovered: Expression = ["boolean", ["feature-state", "hover"], false];

export function campsiteHighlightPaint(base: {
  radius: Value;
  opacity: Value;
  strokeWidth: Value;
  strokeColor: Value;
}) {
  const dimmed = numericToken("--map-campsites-dimmed-opacity", 0.45);
  return {
    radius: [
      "case",
      selected,
      numericToken("--map-campsites-selected-radius", 10),
      hovered,
      numericToken("--map-campsites-hover-radius", 8),
      base.radius,
    ] as Expression,
    opacity: [
      "case",
      selected,
      base.opacity,
      ["==", ["global-state", SELECTED_STATE], true],
      dimmed,
      base.opacity,
    ] as Expression,
    strokeWidth: [
      "case",
      ["any", selected, hovered],
      numericToken("--map-campsites-selected-stroke-width", 3),
      base.strokeWidth,
    ] as Expression,
    strokeColor: [
      "case",
      ["any", selected, hovered],
      token("--map-campsites-selected-stroke"),
      base.strokeColor,
    ] as Expression,
  };
}
