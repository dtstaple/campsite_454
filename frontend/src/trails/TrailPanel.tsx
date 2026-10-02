/**
 * The trail panel (TM05-61): a named route's numbers, its elevation profile, and the
 * campsites along it. Presentational -- TrailInsight owns the data and the map.
 */

import type { ReactNode } from "react";
import type { CampsiteAlong, RouteDetail } from "./api";
import ElevationChart from "./ElevationChart";
import { WITHIN_OPTIONS, duration, feet, miles, naismithMinutes, percent } from "./format";
import { gradeAt, nearestIndex } from "./profile";

export type DetailState =
  | { status: "loading"; name: string }
  | { status: "error"; name: string; message: string }
  | { status: "ready"; detail: RouteDetail };

interface Props {
  state: DetailState;
  cursorM: number | null;
  withinM: number;
  onCursor: (distance: number | null) => void;
  onScrub?: (distance: number) => void;
  onWithin: (metres: number) => void;
  onCampsite: (campsite: CampsiteAlong) => void;
  onClose: () => void;
  /** Extra controls under the chart (the 3D toggle and flythrough, TM05-62). */
  controls?: ReactNode;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="trail-stat" title={hint}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export default function TrailPanel({
  state,
  cursorM,
  withinM,
  onCursor,
  onScrub,
  onWithin,
  onCampsite,
  onClose,
  controls,
}: Props) {
  const name = state.status === "ready" ? state.detail.name : state.name;

  return (
    <aside className="panel trail-panel" aria-label={`Trail: ${name}`}>
      <header className="trail-header">
        <div>
          <div className="panel-subtitle trail-eyebrow">Trail</div>
          <h2 className="trail-name">{name}</h2>
          {state.status === "ready" && state.detail.operator && (
            <div className="trail-meta">{state.detail.operator}</div>
          )}
        </div>
        <button type="button" className="trail-close" onClick={onClose} aria-label="Close trail">
          ×
        </button>
      </header>

      {state.status === "loading" && (
        <div className="trail-status">
          <span className="spinner" />
          Measuring the trail… the first look at a trail samples its elevation: a few seconds,
          up to a minute for a long-distance trail. After that it is instant.
        </div>
      )}
      {state.status === "error" && <div className="trail-status is-error">{state.message}</div>}
      {state.status === "ready" && (
        <Ready
          detail={state.detail}
          cursorM={cursorM}
          withinM={withinM}
          onCursor={onCursor}
          onScrub={onScrub}
          onWithin={onWithin}
          onCampsite={onCampsite}
          controls={controls}
        />
      )}
    </aside>
  );
}

function Ready({
  detail,
  cursorM,
  withinM,
  onCursor,
  onScrub,
  onWithin,
  onCampsite,
  controls,
}: Omit<Props, "state" | "onClose"> & { detail: RouteDetail }) {
  const profile = detail.profile;
  const campsites = detail.campsites;

  return (
    <>
      {profile.status === "ok" ? (
        <>
          <dl className="trail-stats">
            <Stat label="Distance" value={miles(profile.stats.length_m)} hint="Along the stitched route, one way" />
            <Stat label="Gain" value={feet(profile.stats.gain_m)} hint="Smoothed over 100 m, 3 m threshold" />
            <Stat label="Loss" value={feet(profile.stats.loss_m)} />
            <Stat label="High point" value={feet(profile.stats.high_m)} />
            <Stat label="Max grade" value={percent(profile.stats.max_grade_pct)} hint="Steepest 100 m stretch" />
            <Stat
              label="Time"
              value={`≈ ${duration(naismithMinutes(profile.stats.length_m, profile.stats.gain_m))}`}
              hint="Naismith's rule: 1 h per 5 km plus 1 h per 600 m of climb, no breaks"
            />
          </dl>

          <ElevationChart
            distances={profile.distance_m}
            elevations={profile.elevation_m}
            cursorM={cursorM}
            markers={campsites.items.map((site) => ({
              distance: site.distance_along_m,
              label: site.name ?? "Campsite",
            }))}
            onHover={onCursor}
            onScrub={onScrub}
            formatDistance={(m) => miles(m)}
            formatHeight={feet}
          />
          <Readout distances={profile.distance_m} elevations={profile.elevation_m} cursorM={cursorM} />
          {controls}
        </>
      ) : (
        <div className="trail-status">
          Elevation is unavailable right now ({profile.reason}). Distance:{" "}
          {miles(detail.line.length_m)}.
        </div>
      )}

      <section className="trail-campsites" aria-label="Campsites along this trail">
        <div className="trail-campsites-head">
          <div className="panel-subtitle">Campsites along this trail</div>
          <label className="trail-within">
            within
            <select value={withinM} onChange={(event) => onWithin(Number(event.target.value))}>
              {WITHIN_OPTIONS.map((metres) => (
                <option key={metres} value={metres}>
                  {metres < 1000 ? `${metres} m` : `${metres / 1000} km`}
                </option>
              ))}
            </select>
          </label>
        </div>
        {campsites.count === 0 ? (
          <div className="trail-empty">
            No mapped campsites within {withinM < 1000 ? `${withinM} m` : `${withinM / 1000} km`} of
            this trail.
          </div>
        ) : (
          <ol className="trail-campsite-list">
            {campsites.items.map((site) => (
              <li key={site.id}>
                <button
                  type="button"
                  className="trail-campsite"
                  onClick={() => onCampsite(site)}
                  onMouseEnter={() => onCursor(site.distance_along_m)}
                >
                  <span className="trail-mile">mi {(site.distance_along_m / 1609.344).toFixed(1)}</span>
                  <span className="trail-campsite-name">
                    {site.name ?? "Unnamed campsite"}
                    <span className="trail-campsite-off">{Math.round(site.distance_from_route_m)} m off trail</span>
                  </span>
                  {site.score !== null && (
                    <span
                      className="trail-score"
                      title={site.score_breakdown.caps[0]?.reason ?? "Campsite score, 0-100"}
                    >
                      {site.score}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ol>
        )}
        {campsites.truncated && <div className="trail-empty">Showing the first 100.</div>}
      </section>
    </>
  );
}

function Readout({
  distances,
  elevations,
  cursorM,
}: {
  distances: number[];
  elevations: number[];
  cursorM: number | null;
}) {
  if (cursorM === null || distances.length === 0) {
    return <div className="trail-readout is-idle">Hover the profile or the trail</div>;
  }
  const index = nearestIndex(distances, cursorM);
  return (
    <div className="trail-readout">
      <span>mi {(distances[index] / 1609.344).toFixed(2)}</span>
      <span>{feet(elevations[index])}</span>
      <span>{percent(gradeAt(distances, elevations, index))} grade</span>
    </div>
  );
}
