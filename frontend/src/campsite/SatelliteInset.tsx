/**
 * A small, non-interactive satellite picture centred on a campsite (TM05-66): a few Esri
 * World Imagery tiles (TM05-65) positioned so the site sits in the middle. Plain <img>
 * elements rather than a second map, because nothing here needs panning or zooming.
 */

import { IMAGERY_ATTRIBUTION } from "../basemap/satellite";
import { insetTiles } from "./inset";

const WIDTH = 328;
const HEIGHT = 150;

export default function SatelliteInset({ lon, lat }: { lon: number; lat: number }) {
  const attribution = IMAGERY_ATTRIBUTION.replace(/<[^>]+>/g, "");
  return (
    <figure className="campsite-inset" aria-label="Satellite view of the campsite">
      <div className="campsite-inset-frame" style={{ width: WIDTH, height: HEIGHT }}>
        {insetTiles(lon, lat, WIDTH, HEIGHT).map((tile) => (
          <img
            key={tile.url}
            src={tile.url}
            alt=""
            width={256}
            height={256}
            draggable={false}
            style={{ left: tile.left, top: tile.top }}
          />
        ))}
        <span className="campsite-inset-pin" aria-hidden="true" />
      </div>
      <figcaption>{attribution}</figcaption>
    </figure>
  );
}
