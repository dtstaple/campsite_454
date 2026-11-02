/**
 * Who has the map in 3D, and whether that is remembered (TM05-144).
 *
 * 3D can be turned on from two places: the main map's 3D button, and the trail panel
 * (its 3D button, or Fly the trail, which turns 3D on by itself). The rules:
 *
 * - A 3D button press is the hiker's choice: it is remembered across reloads, and closing
 *   the trail panel leaves it on.
 * - Fly the trail turning 3D on is not a choice: closing the panel takes the map back to
 *   2D, as it always has, and a reload starts flat.
 *
 * Pure so the rules are testable without a map; useThreeD applies them to MapLibre.
 */

export type ThreeDOwner = "user" | "flythrough";

export interface ThreeDState {
  on: boolean;
  /** What turned 3D on; null while off. */
  by: ThreeDOwner | null;
}

export const OFF: ThreeDState = { on: false, by: null };

/** A 3D button press, from either the map or the trail panel. */
export function pressed(on: boolean): ThreeDState {
  return on ? { on: true, by: "user" } : OFF;
}

/** Fly the trail: 3D on if it isn't already, without taking over a choice the user made. */
export function flown(state: ThreeDState): ThreeDState {
  return state.on ? state : { on: true, by: "flythrough" };
}

/** The trail panel closed: only 3D the flythrough turned on goes away with it. */
export function panelClosed(state: ThreeDState): ThreeDState {
  return state.by === "flythrough" ? OFF : state;
}

/** Pitch for 3D switched on from the main map, where no trail camera takes over. */
export const MAP_3D_PITCH = 60;

export const STORAGE_KEY = "campsite.threeD";

type Store = Pick<Storage, "getItem" | "setItem">;

/** The remembered choice. Storage can throw (private mode, blocked): then it's flat. */
export function readStored(store: Store | undefined): ThreeDState {
  try {
    return store?.getItem(STORAGE_KEY) === "on" ? pressed(true) : OFF;
  } catch {
    return OFF;
  }
}

/** Remember only the user's own choice; a flythrough's 3D is never written. */
export function writeStored(store: Store | undefined, state: ThreeDState): void {
  if (state.by === "flythrough") return;
  try {
    store?.setItem(STORAGE_KEY, state.on ? "on" : "off");
  } catch {
    /* not remembered; still applied */
  }
}
