/**
 * Mode-driven layer ordering and visibility, kept outside map/layers.ts.
 *
 * layers.ts is the single place map layers are *defined*; this module only decides how
 * the active mode presents them. If the two are merged later, `orderedLayers` is the
 * piece that belongs beside LAYERS -- see the run summary in
 * artifacts/ui-direction-audit.md.
 */

import { LAYERS } from "../map/layers";
import type { LayerName } from "../api";
import type { ActivityMode } from "./modes";

export type LayerEntry = (typeof LAYERS)[number];

/** LAYERS in the mode's emphasis order. Layers the mode does not mention go last. */
export function orderedLayers(mode: ActivityMode): LayerEntry[] {
  const rank = (name: LayerName) => {
    const index = mode.emphasis.indexOf(name);
    return index === -1 ? mode.emphasis.length : index;
  };
  return [...LAYERS].sort((a, b) => rank(a.name) - rank(b.name));
}

/** The layer the mode is about, which the panel emphasises. */
export function primaryLayer(mode: ActivityMode): LayerName | undefined {
  return mode.emphasis[0];
}
