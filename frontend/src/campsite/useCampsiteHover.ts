/**
 * Hovering a row in the trail panel's campsite list lights up that site's circle
 * (TM05-69): feature-state `hover` on the campsite source, read by highlight.ts.
 */

import { useEffect } from "react";
import type * as maplibregl from "maplibre-gl";

const CAMPSITE_SOURCE = "campsites";

/** feature-state `hover` on one campsite circle while a trail-list row is hovered. */
export function useCampsiteHover(map: maplibregl.Map | null, id: string | null): void {
  useEffect(() => {
    if (!map || !id || !map.getSource(CAMPSITE_SOURCE)) return;
    const target = { source: CAMPSITE_SOURCE, id };
    map.setFeatureState(target, { hover: true });
    return () => {
      if (map.getSource(CAMPSITE_SOURCE)) map.setFeatureState(target, { hover: false });
    };
  }, [map, id]);
}
