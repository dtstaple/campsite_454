/**
 * The map's 3D terrain, shared by the main map's 3D button and the trail panel (TM05-144).
 *
 * One owner for setTerrain, so the two controls can never disagree: both read `is3D` and
 * change it through this hook, and the rules for who turned it on live in threeD.ts.
 * The terrain source is added once on load and never removed (map/layers.ts), and the
 * basemap and mode switches only show and hide layers, so 3D survives both.
 *
 * Terrain is applied synchronously in each action, not in an effect: the trail panel
 * places its camera at a pitch above the 2D limit straight after turning 3D on, so the
 * limit has to be raised by then.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type * as maplibregl from "maplibre-gl";
import { disable3D, enable3D, prefersReducedMotion } from "../trails/terrain3d";
import {
  flown,
  MAP_3D_PITCH,
  panelClosed,
  pressed,
  readStored,
  writeStored,
  type ThreeDState,
} from "./threeD";

export interface ThreeD {
  is3D: boolean;
  /** A 3D button. `tilt` eases the camera up, for the main map; the trail panel places its own. */
  set3D: (on: boolean, options?: { tilt?: boolean }) => void;
  /** Fly the trail is starting. */
  fly: () => void;
  /** The trail panel closed. */
  panelClosed: () => void;
}

function storage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function useThreeD(map: maplibregl.Map | null): ThreeD {
  const [state, setState] = useState<ThreeDState>(() => readStored(storage()));
  const stateRef = useRef(state);
  // The map terrain is on for, and the pitch limit to restore when it goes off.
  const applied = useRef<{ map: maplibregl.Map; previousMaxPitch: number } | null>(null);

  const apply = useCallback(
    (next: ThreeDState, tilt: boolean) => {
      stateRef.current = next;
      setState(next);
      if (!map) return;
      if (next.on && applied.current?.map !== map) {
        applied.current = { map, previousMaxPitch: enable3D(map) };
        if (tilt && map.getPitch() < MAP_3D_PITCH / 2) {
          map.easeTo({ pitch: MAP_3D_PITCH, duration: prefersReducedMotion() ? 0 : 600 });
        }
      } else if (!next.on && applied.current?.map === map) {
        disable3D(map, applied.current.previousMaxPitch);
        applied.current = null;
      }
    },
    [map],
  );

  // A remembered 3D comes back once the map (and its terrain source) exists, tilted.
  useEffect(() => {
    if (map && stateRef.current.on && applied.current?.map !== map) apply(stateRef.current, true);
  }, [map, apply]);

  const set3D = useCallback(
    (on: boolean, options?: { tilt?: boolean }) => {
      const next = pressed(on);
      writeStored(storage(), next);
      apply(next, Boolean(options?.tilt));
    },
    [apply],
  );

  const fly = useCallback(() => apply(flown(stateRef.current), false), [apply]);
  const closed = useCallback(() => apply(panelClosed(stateRef.current), false), [apply]);

  return { is3D: state.on, set3D, fly, panelClosed: closed };
}
