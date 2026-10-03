/**
 * Applies the basemap choice to the map (TM05-65). Renders nothing.
 *
 * Adds the imagery layers once the map exists, shows or hides them, and owns the one
 * interaction with the hillshade: over imagery the hillshade is hidden, because terrain
 * shading on top of photographed shadows reads as mud. When satellite goes off, the
 * hillshade returns to whatever the Terrain shading toggle says.
 */

import { useEffect } from "react";
import type * as maplibregl from "maplibre-gl";
import { setHillshadeVisible } from "../map/layers";
import { addImageryLayers, setImageryVisible } from "./satellite";
import type { Basemap } from "./useBasemap";

interface Props {
  map: maplibregl.Map | null;
  basemap: Basemap;
  terrain: boolean;
}

export default function SatelliteLayers({ map, basemap, terrain }: Props) {
  useEffect(() => {
    if (!map) return;
    addImageryLayers(map);
    const satellite = basemap === "satellite";
    setImageryVisible(map, satellite);
    setHillshadeVisible(map, terrain && !satellite);
  }, [map, basemap, terrain]);
  return null;
}
