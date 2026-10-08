/**
 * Floating layer panel for the map, driven by the active activity mode.
 *
 * Replaces the old fixed sidebar. Layers are listed in the mode's emphasis order with
 * the primary one emphasised; counts and zoom hints are kept but set quietly, because
 * they are diagnostics rather than the thing the user came to read.
 */

import { Fragment, useState } from "react";
import {
  layerVisibleAtZoom,
  MIN_ZOOM_FOR_LINEWORK,
  type LayerName,
  type Metadata,
} from "../api";
import { orderedLayers } from "../map/layers";
import { primaryLayer, type ActivityMode } from "../modes/modes";
import { REGIONS, type Region } from "../regions";
import { CONTOUR_MIN_ZOOM } from "../map/contourConfig";
import { bandLabel, GRADES, gradeToken } from "../score/grade";

interface Props {
  mode: ActivityMode;
  enabled: Record<LayerName, boolean>;
  meta: Partial<Record<LayerName, Metadata>>;
  zoom: number;
  loading: boolean;
  fromCache: boolean;
  currentRegionId: string | undefined;
  onToggle: (layer: LayerName, on: boolean) => void;
  terrain: boolean;
  onTerrain: (on: boolean) => void;
  /** TM05-83: contour lines, drawn from zoom CONTOUR_MIN_ZOOM. */
  contours: boolean;
  onContours: (on: boolean) => void;
  onRegion: (region: Region) => void;
}

/** What the campsite marker colours mean (TM05-48). Shown while the layer is on. */
function ScoreLegend() {
  return (
    <ul className="score-legend" aria-label="Campsite score colours">
      {GRADES.map((grade) => (
        <li key={grade.letter}>
          <span className="swatch" style={{ background: `var(${gradeToken(grade.letter)})` }} />
          {bandLabel(grade.letter)}
        </li>
      ))}
      <li>
        <span className="swatch" style={{ background: `var(${gradeToken(null)})` }} />
        No score yet
      </li>
    </ul>
  );
}

/** "1,204" or "500 / 1,204" when the API capped the response. */
function countLabel(info: Metadata | undefined): string {
  if (!info) return "";
  const returned = info.returned.toLocaleString();
  return info.truncated ? `${returned} / ${info.matched.toLocaleString()}` : returned;
}

export default function LayerPanel({
  mode,
  enabled,
  meta,
  zoom,
  loading,
  fromCache,
  currentRegionId,
  onToggle,
  terrain,
  onTerrain,
  contours,
  onContours,
  onRegion,
}: Props) {
  const [open, setOpen] = useState(true);
  const primary = primaryLayer(mode);

  return (
    <section className="panel layer-panel" aria-label="Map layers">
      <button
        type="button"
        className="panel-toggle"
        aria-expanded={open}
        onClick={() => setOpen((previous) => !previous)}
      >
        <span className="panel-title">Layers</span>
        {loading && <span className="spinner" aria-label="Loading" />}
        <span className="panel-chevron" aria-hidden="true">
          {open ? "−" : "+"}
        </span>
      </button>

      {open && (
        <>
          {orderedLayers(mode).map((layer) => {
            const on = enabled[layer.name];
            const zoomedOut = !layerVisibleAtZoom(layer.name, zoom);
            const classes = [
              "row",
              on && !zoomedOut ? "" : "off",
              layer.name === primary ? "is-primary" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <Fragment key={layer.name}>
                <label className={classes}>
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={(event) => onToggle(layer.name, event.target.checked)}
                  />
                  {/* Campsites are drawn in grade colours, so their swatch is the grades. */}
                  {layer.name === "campsites" ? (
                    <span className="swatch swatch-score" />
                  ) : (
                    <span className="swatch" style={{ background: `var(--map-${layer.name})` }} />
                  )}
                  {layer.label}
                  <span className="count">
                    {on && zoomedOut
                      ? `zoom ${MIN_ZOOM_FOR_LINEWORK}+`
                      : on
                        ? countLabel(meta[layer.name])
                        : ""}
                  </span>
                </label>
                {layer.name === "campsites" && on && <ScoreLegend />}
              </Fragment>
            );
          })}

          {/* Not an API layer: shading the map draws by itself, so it has no count. */}
          <label className={`row${terrain ? "" : " off"}`}>
            <input
              type="checkbox"
              checked={terrain}
              onChange={(event) => onTerrain(event.target.checked)}
            />
            <span className="swatch swatch-terrain" />
            Terrain shading
          </label>
          <label className={`row${contours ? "" : " off"}`}>
            <input
              type="checkbox"
              checked={contours}
              onChange={(event) => onContours(event.target.checked)}
            />
            <span className="swatch swatch-contours" />
            Contours
            <span className="count">
              {contours && zoom < CONTOUR_MIN_ZOOM ? `zoom ${CONTOUR_MIN_ZOOM}+` : contours ? "ft" : ""}
            </span>
          </label>

          {/* Data sits in a few regions hundreds of miles apart, so free panning mostly
              finds empty map. These jump straight to the places that have something. */}
          <div className="panel-subtitle">Regions</div>
          <div className="regions" role="group" aria-label="Jump to a region">
            {REGIONS.map((region) => {
              const isCurrent = region.id === currentRegionId;
              return (
                <button
                  key={region.id}
                  type="button"
                  className={`region-button${isCurrent ? " is-current" : ""}`}
                  aria-pressed={isCurrent}
                  onClick={() => onRegion(region)}
                >
                  {region.label}
                </button>
              );
            })}
          </div>

          {fromCache && !loading && (
            <div className="status cached">Cached · zoom {zoom.toFixed(1)}</div>
          )}
        </>
      )}
    </section>
  );
}
