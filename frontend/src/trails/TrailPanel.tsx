/**
 * The trail panel (TM05-61): a named route's numbers, its elevation profile, and the
 * campsites along it. Presentational -- TrailInsight owns the data and the map.
 */

import type { ReactNode } from "react";
import type { CampsiteAlong, RouteDetail } from "./api";
import ElevationChart from "./ElevationChart";
import {
  WITHIN_OPTIONS,
  campsiteName,
  campsitePlace,
  duration,
  feet,
  isAlong,
  miles,
  naismithMinutes,
  percent,
  routeTypeText,
} from "./format";
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
  /** A list row is hovered or focused (TM05-69), or null when it no longer is. */
  onCampsiteHover?: (campsite: CampsiteAlong | null) => void;
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
  onCampsiteHover,
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
          {state.status === "ready" && state.detail.assembled && state.detail.assembly && (
            <div
              className="trail-meta trail-assembled"
              title={`Not a mapped route: ${state.detail.assembly.ways} segments named "${name}", joined where they meet`}
            >
              {state.detail.assembly.note}
            </div>
          )}
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
          onCampsiteHover={onCampsiteHover}
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
  onCampsiteHover,
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
            {detail.difficulty && (
              <Stat
                label="Difficulty"
                value={detail.difficulty.label}
                hint={`Shenandoah rating ${detail.difficulty.shenandoah}: ${detail.difficulty.formula}`}
              />
            )}
            {detail.route_type && (
              <Stat label="Type" {...routeTypeText(detail.route_type)} />
            )}
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
            markers={campsites.items.filter(isAlong).map((site) => ({
              distance: site.distance_along_m,
              label: campsiteName(site).text,
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
                  onMouseEnter={() => {
                    // Past either end there is no point on the profile to show (TM05-73).
                    onCursor(isAlong(site) ? site.distance_along_m : null);
                    onCampsiteHover?.(site);
                  }}
                  onMouseLeave={() => onCampsiteHover?.(null)}
                  onFocus={() => onCampsiteHover?.(site)}
                  onBlur={() => onCampsiteHover?.(null)}
                >
                  <span className="trail-mile" title={site.position_label ?? undefined}>
                    {campsitePlace(site).mile}
                  </span>
                  <span className="trail-campsite-name">
                    <span
                      className={campsiteName(site).derived ? "is-derived" : undefined}
                      title={
                        campsiteName(site).derived
                          ? "No name in the source data; named from what is nearby"
                          : undefined
                      }
                    >
                      {campsiteName(site).text}
                    </span>
                    <span className="trail-campsite-off">{campsitePlace(site).off}</span>
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
