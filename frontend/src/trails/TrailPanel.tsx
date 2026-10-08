/**
 * The trail panel (TM05-61): a named route's numbers, its elevation profile, and the
 * campsites along it. Presentational -- TrailInsight owns the data and the map.
 */

import { useState, type MouseEvent, type ReactNode } from "react";
import { API_BASE_URL } from "../api";
import { authHeaders } from "../auth";
import { useSession } from "../session";
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
import { alongResults, searchSummary, type Candidate, type CandidateSearch } from "./candidates";
import { byMile, junctionMiles, type Connection } from "./connections";
import { gpxFilename, gpxPath } from "./gpx";
import SaveTrail from "./SaveTrail";
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
  /** The overnight plan section (TM05-81), under the GPX download. */
  planner?: ReactNode;
  /** TM05-81: the Night button on each campsite row; omitted when signed out. */
  stops?: StopChoice;
  /** TM05-99: the "Find campsites along this trail" search. */
  finder: Finder;
  onFind: () => void;
  onCandidate: (candidate: Candidate) => void;
  /** TM05-101: open a connecting trail; hover shows its junctions on the map. */
  onConnection?: (connection: Connection) => void;
  onConnectionHover?: (connection: Connection | null) => void;
}

export interface StopChoice {
  ids: readonly string[];
  /** The night each chosen stop falls on, once the server has ordered them. */
  nightOf: Readonly<Record<string, number>>;
  /** Add or remove a stop by id: a campsite's source_id, or a candidate's id. */
  onToggle: (id: string) => void;
}

/** TM05-99: where the trail's campsite search is. Nothing is shown until it is asked for. */
export type Finder =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; search: CandidateSearch | null }
  | { status: "error"; message: string };

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
  planner,
  stops,
  finder,
  onFind,
  onCandidate,
  onConnection,
  onConnectionHover,
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
          planner={planner}
          stops={stops}
          finder={finder}
          onFind={onFind}
          onCandidate={onCandidate}
          onConnection={onConnection}
          onConnectionHover={onConnectionHover}
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
  planner,
  stops,
  finder,
  onFind,
  onCandidate,
  onConnection,
  onConnectionHover,
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
            markers={(finder.status === "idle" ? [] : campsites.items.filter(isAlong)).map((site) => ({
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

      {detail.connections && detail.connections.length > 0 && (
        <section className="trail-connections" aria-label="Connecting trails">
          <div className="panel-subtitle">Connects to</div>
          <ul>
            {byMile(detail.connections).map((connection) => (
              <li key={`${connection.osm_id ?? connection.way_id}`}>
                <button
                  type="button"
                  className="trail-connection"
                  onClick={() => onConnection?.(connection)}
                  onMouseEnter={() => onConnectionHover?.(connection)}
                  onMouseLeave={() => onConnectionHover?.(null)}
                  onFocus={() => onConnectionHover?.(connection)}
                  onBlur={() => onConnectionHover?.(null)}
                >
                  <span className="trail-connection-name">{connection.name}</span>
                  <span className="trail-connection-mile">{junctionMiles(connection)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <GpxDownload detail={detail} withinM={withinM} />
      {planner}

      <section className="trail-campsites" aria-label="Places to camp along this trail">
        <div className="trail-campsites-head">
          <div className="panel-subtitle">Places to camp</div>
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

        {finder.status === "idle" ? (
          <div className="trail-find">
            <p className="trail-find-prompt">
              Planning an overnight? Find places to camp along this trail.
            </p>
            <button type="button" className="button-primary trail-find-button" onClick={onFind}>
              Find campsites along this trail
            </button>
          </div>
        ) : (
          <>
            {finder.status === "loading" && (
              <div className="trail-status">
                <span className="spinner" />
                Searching for potential spots: public land, 150 ft from trails and water, DEC
                elevation limits, gentle ground. The first search of a trail samples the
                terrain and can take up to half a minute; after that it is instant.
              </div>
            )}
            {finder.status === "error" && (
              <div className="trail-status is-error">{finder.message}</div>
            )}
            <AlongList
              campsites={campsites.items}
              search={finder.status === "ready" ? finder.search : null}
              stops={stops}
              withinM={withinM}
              onCampsite={onCampsite}
              onCandidate={onCandidate}
              onCursor={onCursor}
              onCampsiteHover={onCampsiteHover}
            />
            {finder.status === "ready" && finder.search?.reason && (
              <div className="trail-empty">{finder.search.reason}</div>
            )}
            {campsites.truncated && <div className="trail-empty">Showing the first 100.</div>}
          </>
        )}
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

/**
 * TM05-79: the trail as a GPX file, with the campsites currently listed as waypoints.
 * Signed in, the file also carries the user's own waypoints near the trail (TM05-80); the
 * API authenticates with a token header, which a plain link cannot send, so that download
 * is fetched and saved from a blob instead.
 */
function GpxDownload({ detail, withinM }: { detail: RouteDetail; withinM: number }) {
  const { session } = useSession();
  const [failed, setFailed] = useState<string | null>(null);
  const path = gpxPath(detail, withinM);
  if (!path) return null;
  const url = `${API_BASE_URL}${path}`;

  const download = async (event: MouseEvent<HTMLAnchorElement>) => {
    if (!session) return; // the plain link does it
    event.preventDefault();
    setFailed(null);
    try {
      const response = await fetch(url, { headers: authHeaders(session) });
      if (!response.ok) throw new Error(`The server answered ${response.status}.`);
      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = gpxFilename(detail.name);
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    } catch (error) {
      setFailed(`Download failed: ${(error as Error).message}`);
    }
  };

  const within = withinM < 1000 ? `${withinM} m` : `${withinM / 1000} km`;
  return (
    <div className="trail-actions">
      {/* Signed out, a plain link: the API answers with Content-Disposition: attachment, so
          the browser saves the file (the download attribute is ignored across origins). */}
      <SaveTrail detail={detail} />
      <a className="trail-3d-button trail-gpx" href={url} download onClick={download}>
        Download GPX
      </a>
      <span className="trail-3d-hint">
        Track and campsites within {within}
        {session ? ", plus your waypoints" : ""}
      </span>
      {failed && <span className="trail-gpx-error">{failed}</span>}
    </div>
  );
}

/** TM05-81: choose a place as an overnight stop, or take it out of the plan. */
function StopButton({
  id,
  label,
  along,
  stops,
}: {
  id: string;
  label: string;
  along: boolean;
  stops: StopChoice;
}) {
  const chosen = stops.ids.includes(id);
  const night = stops.nightOf[id];
  return (
    <button
      type="button"
      className="trail-stop"
      aria-pressed={chosen}
      disabled={!along && !chosen}
      title={
        along
          ? chosen
            ? `Remove ${label} from the plan`
            : `Stop overnight at ${label}`
          : "Past the end of the trail, so it cannot be a stop along it"
      }
      onClick={() => stops.onToggle(id)}
    >
      {chosen ? (night ? `Night ${night}` : "Night") : "+ Night"}
    </button>
  );
}

/**
 * TM05-99: mapped campsites and potential spots in one list, by mile. A potential spot is
 * labelled as unverified and drawn with its own dashed style, never the score colours.
 */
function AlongList({
  campsites,
  search,
  stops,
  withinM,
  onCampsite,
  onCandidate,
  onCursor,
  onCampsiteHover,
}: {
  campsites: CampsiteAlong[];
  search: CandidateSearch | null;
  stops?: StopChoice;
  withinM: number;
  onCampsite: (campsite: CampsiteAlong) => void;
  onCandidate: (candidate: Candidate) => void;
  onCursor: (distance: number | null) => void;
  onCampsiteHover?: (campsite: CampsiteAlong | null) => void;
}) {
  const rows = alongResults(campsites, search?.candidates ?? []);
  const within = withinM < 1000 ? `${withinM} m` : `${withinM / 1000} km`;
  if (rows.length === 0 && search) {
    return (
      <div className="trail-empty">
        No mapped campsites or potential spots within {within} of this trail.
      </div>
    );
  }
  return (
    <>
      <div className="trail-find-summary">{searchSummary(campsites.length, search)}</div>
      <ol className="trail-campsite-list">
        {rows.map((row) =>
          row.kind === "campsite" ? (
            <li key={row.id}>
              <button
                type="button"
                className="trail-campsite"
                onClick={() => onCampsite(row.site)}
                onMouseEnter={() => {
                  // Past either end there is no point on the profile to show (TM05-73).
                  onCursor(isAlong(row.site) ? row.site.distance_along_m : null);
                  onCampsiteHover?.(row.site);
                }}
                onMouseLeave={() => onCampsiteHover?.(null)}
                onFocus={() => onCampsiteHover?.(row.site)}
                onBlur={() => onCampsiteHover?.(null)}
              >
                <span className="trail-mile" title={row.site.position_label ?? undefined}>
                  {campsitePlace(row.site).mile}
                </span>
                <span className="trail-campsite-name">
                  <span
                    className={campsiteName(row.site).derived ? "is-derived" : undefined}
                    title={
                      campsiteName(row.site).derived
                        ? "No name in the source data; named from what is nearby"
                        : undefined
                    }
                  >
                    {campsiteName(row.site).text}
                  </span>
                  <span className="trail-campsite-off">{campsitePlace(row.site).off}</span>
                </span>
                {row.site.score !== null && (
                  <span
                    className="trail-score"
                    title={row.site.score_breakdown.caps[0]?.reason ?? "Campsite score, 0-100"}
                  >
                    {row.site.score}
                  </span>
                )}
              </button>
              {stops && (
                <StopButton
                  id={row.id}
                  label={campsiteName(row.site).text}
                  along={isAlong(row.site)}
                  stops={stops}
                />
              )}
            </li>
          ) : (
            <li key={row.id} className="is-candidate">
              <button
                type="button"
                className="trail-campsite"
                onClick={() => onCandidate(row.candidate)}
                onMouseEnter={() => onCursor(row.candidate.distance_along_m)}
              >
                <span className="trail-mile">
                  mi {(row.candidate.distance_along_m / 1609.344).toFixed(1)}
                </span>
                <span className="trail-campsite-name">
                  <span className="trail-candidate-label">{row.candidate.label}</span>
                  <span className="trail-campsite-off">
                    {Math.round(row.candidate.distance_from_route_m)} m off trail ·{" "}
                    {row.candidate.slope_deg.toFixed(0)}° slope
                  </span>
                </span>
                {row.candidate.score !== null && (
                  <span className="trail-score trail-candidate-score" title="Computed score, 0-100">
                    {row.candidate.score}
                  </span>
                )}
              </button>
              {stops && (
                <StopButton id={row.id} label={row.candidate.label} along stops={stops} />
              )}
            </li>
          ),
        )}
      </ol>
    </>
  );
}
