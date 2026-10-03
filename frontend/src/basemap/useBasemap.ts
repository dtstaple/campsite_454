/**
 * The chosen basemap, remembered across reloads (TM05-65).
 *
 * localStorage is a per-browser convenience here, nothing more: every access is wrapped,
 * because it can throw (private mode, blocked storage) and the map must still work.
 */

import { useCallback, useState } from "react";

export type Basemap = "standard" | "satellite";

const STORAGE_KEY = "campsite.basemap";

function read(): Basemap {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "satellite" ? "satellite" : "standard";
  } catch {
    return "standard";
  }
}

export function useBasemap(): [Basemap, (next: Basemap) => void] {
  const [basemap, setBasemap] = useState<Basemap>(read);
  const choose = useCallback((next: Basemap) => {
    setBasemap(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* not remembered; still applied */
    }
  }, []);
  return [basemap, choose];
}
