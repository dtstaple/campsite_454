/**
 * The campsite panel's Terrain section (TM05-142): pooling risk, sun, shelter and view,
 * from the terrain pipeline's precomputed facts, so it shows instantly with the panel.
 * Wording lives in terrain/terrain.ts. "Show what I can see" draws the site's viewshed
 * on the map. Every estimate carries the bare-earth caveat.
 */

import { terrainLines, type TerrainPayload } from "../terrain/terrain";

interface Props {
  terrain: TerrainPayload;
  /** Whether the viewshed is on the map now. */
  showing: boolean;
  onToggleView: () => void;
}

export default function TerrainSection({ terrain, showing, onToggleView }: Props) {
  const lines = terrainLines(terrain);
  if (lines.length === 0) return null;
  return (
    <section className="campsite-terrain" aria-label="Terrain">
      <div className="panel-subtitle">Terrain</div>
      <dl className="campsite-facts">
        {lines.map((line) => (
          <div key={line.key} className="campsite-row">
            <dt>{line.label}</dt>
            <dd>
              <span className={line.tone ? `terrain-value is-${line.tone}` : "terrain-value"}>{line.value}</span>
              {line.detail && <span className="campsite-sub">{line.detail}</span>}
            </dd>
          </div>
        ))}
      </dl>
      {terrain.has_viewshed && (
        <button type="button" className="terrain-view-button" aria-pressed={showing} onClick={onToggleView}>
          {showing ? "Hide what I can see" : "Show what I can see"}
        </button>
      )}
      <p className="terrain-note">{terrain.note}</p>
    </section>
  );
}
