/**
 * Activity modes: what the map is for right now.
 *
 * A mode is configuration, not behaviour. Each one declares which layers start visible
 * and which it puts first, and the page reads that rather than branching on the mode
 * id. Adding a mode means adding an entry here; nothing else should need an `if`.
 *
 * Backcountry Ski is defined so the shape of the config is settled before it is needed,
 * but `enabled: false` keeps it out of the UI entirely. It needs slope-angle shading
 * from 3DEP before it would be honest to offer -- see artifacts/ui-direction-audit.md.
 */

import type { LayerName } from "../api";

export type ModeId = "hiking" | "camping" | "backcountry-ski";

/** Keys into the original icon set in ./icons.tsx. */
export type ModeIconId = "hiking" | "camping" | "ski";

export interface ActivityMode {
  id: ModeId;
  label: string;
  icon: ModeIconId;
  /** Disabled modes are type-checked like any other but never rendered. */
  enabled: boolean;
  /** Which layers are on when the user switches into this mode. */
  layers: Readonly<Record<LayerName, boolean>>;
  /** Whether terrain hillshading starts on. Not an API layer, so kept separate. */
  terrain: boolean;
  /**
   * Layers in the order the layer panel lists them, most important first. The first
   * entry is the mode's primary layer and is visually emphasised.
   */
  emphasis: readonly LayerName[];
}

export const MODES: readonly ActivityMode[] = [
  {
    id: "hiking",
    label: "Hiking",
    icon: "hiking",
    enabled: true,
    // Hiking is about the trail network. Campsites start off so they do not crowd it;
    // one click brings them back.
    layers: { trails: true, water: true, "public-land": true, campsites: false },
    terrain: true,
    emphasis: ["trails", "water", "public-land", "campsites"],
  },
  {
    id: "camping",
    label: "Camping",
    icon: "camping",
    enabled: true,
    // TM05-99: mapped campsites start off in every mode. Hikers find places to camp
    // with the trail panel's "Find campsites along this trail"; the layer is one click away.
    layers: { trails: true, water: true, "public-land": true, campsites: false },
    terrain: true,
    emphasis: ["campsites", "water", "public-land", "trails"],
  },
  {
    id: "backcountry-ski",
    label: "Backcountry Ski",
    icon: "ski",
    enabled: false,
    layers: { trails: true, water: false, "public-land": true, campsites: false },
    terrain: true,
    emphasis: ["trails", "public-land", "water", "campsites"],
  },
];

/** The layer the mode is about, which the layer panel emphasises. */
export function primaryLayer(mode: ActivityMode): LayerName | undefined {
  return mode.emphasis[0];
}

/** The only modes the UI may show. */
export const ENABLED_MODES: readonly ActivityMode[] = MODES.filter((mode) => mode.enabled);

export const DEFAULT_MODE_ID: ModeId = "hiking";

/**
 * Look a mode up by id, falling back to the default for an unknown or disabled one --
 * so a stale id can never surface a mode that is meant to be hidden.
 */
export function modeById(id: ModeId): ActivityMode {
  return (
    ENABLED_MODES.find((mode) => mode.id === id) ??
    ENABLED_MODES.find((mode) => mode.id === DEFAULT_MODE_ID) ??
    ENABLED_MODES[0]
  );
}
