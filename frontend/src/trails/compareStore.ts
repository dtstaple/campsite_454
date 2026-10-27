/**
 * The trails being compared (TM05-121), shared by the trail panel, the Discover cards and
 * the tray, and remembered in localStorage so the list survives moving between the map and
 * Discover. The list logic itself is in compare.ts.
 */

import { useSyncExternalStore } from "react";
import { addTrail, parseCompared, removeTrail, type AddResult, type ComparedTrail } from "./compare";

const STORAGE_KEY = "campsite.compare";

function read(): ComparedTrail[] {
  try {
    return parseCompared(localStorage.getItem(STORAGE_KEY));
  } catch {
    return [];
  }
}

let current: ComparedTrail[] = read();
const listeners = new Set<() => void>();

function set(list: ComparedTrail[]) {
  current = list;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    /* not remembered across reloads; still shared in this tab */
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function addCompared(trail: ComparedTrail): AddResult["status"] {
  const result = addTrail(current, trail);
  if (result.status === "added") set(result.list);
  return result.status;
}

export function removeCompared(key: string) {
  set(removeTrail(current, key));
}

export function clearCompared() {
  set([]);
}

export function useCompared(): ComparedTrail[] {
  return useSyncExternalStore(subscribe, () => current);
}
