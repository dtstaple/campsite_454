/**
 * The tracking display (TM05-111): a small panel on a desktop, a bottom sheet on a phone.
 * The sheet opens at half, with the numbers that matter at a glance, the controls and the
 * screen-lock note on top; at peek just the glance row shows. It is honest about the
 * limits of tracking in a phone browser.
 *
 * Also draws the breadcrumb: the recorded track, one line per segment, so a pause or a
 * hidden stretch is a visible gap rather than a straight line across it.
 */

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import * as maplibregl from "maplibre-gl";
import Sheet from "../components/Sheet";
import { token } from "../theme";
import { duration, miles } from "../trails/format";
import { TRACKING } from "./config";
import { clock, defaultHikeName, feetOrDash, gainFeet, pace } from "./format";
import { glanceItems } from "./glance";
import { farFromTrailNote, trailLine, trailProgress } from "./progress";
import { SPEEDS } from "./simulate";
import { hikeStats, trackLines } from "./track";
import type { Hike } from "./useHike";
import { useWakeLock } from "./useWakeLock";
import "./tracking.css";

const SOURCE = "hike-track";
const LINE = "hike-track-line";

interface Props {
  map: maplibregl.Map | null;
  hike: Hike;
  signedIn: boolean;
}

export default function HikePanel({ map, hike, signedIn }: Props) {
  const { recording, now } = hike;
  useBreadcrumb(map, recording ? trackLines(recording) : null);
  const wakeLock = useWakeLock(recording?.status === "running");
  if (!recording) return null;

  const stats = hikeStats(recording, now);
  const position = recording.last ? ([recording.last.lon, recording.last.lat] as [number, number]) : null;
  const progress =
    recording.trail && position
      ? trailProgress(recording.trail, position, recording.direction ?? 1, stats)
      : null;
  const firstPoint = recording.segments[0]?.points[0];
  const farNote =
    recording.trail && firstPoint ? farFromTrailNote(trailLine(recording.trail), [firstPoint.lon, firstPoint.lat]) : null;
  const status = recording.status;

  return (
    <Sheet className="panel hike-panel" label="Hike tracking" initial="half">
      <header className="hike-head">
        <div>
          <div className="panel-subtitle">
            {recording.mode === "trail" ? "Hiking" : "Free walk"}
            {recording.simulated && <span className="hike-simulated">Simulated</span>}
          </div>
          <div className="hike-title">{recording.trail?.name ?? "Tracking anywhere"}</div>
        </div>
        <span className={`hike-status is-${status}${stats.stoppedNow ? " is-halted" : ""}`} role="status">
          {status === "running" ? (stats.stoppedNow ? "Not moving" : position ? "Recording" : "Waiting for GPS…") : status === "paused" ? "Paused" : "Finished"}
        </span>
      </header>

      <dl className="hike-glance">
        {glanceItems(stats, progress).map((item) => (
          <Stat key={item.label} label={item.label} value={item.value} />
        ))}
      </dl>

      {progress?.offTrail && (
        <div className="hike-warn" role="alert">
          Off trail: {Math.round(progress.offM)} m from {recording.trail?.name}.
        </div>
      )}

      {status !== "stopped" ? (
        <div className="hike-controls">
          {status === "running" ? (
            <button type="button" className="trail-3d-button" onClick={hike.pause}>
              Pause
            </button>
          ) : (
            <button type="button" className="trail-3d-button is-active" onClick={hike.resume}>
              Resume
            </button>
          )}
          <button type="button" className="trail-3d-button hike-stop" onClick={hike.stop}>
            Stop
          </button>
        </div>
      ) : (
        <Finish hike={hike} signedIn={signedIn} defaultName={defaultHikeName(recording.trail?.name ?? null, recording.startedAt)} />
      )}

      {recording.simulation && status !== "stopped" && (
        <div className="hike-speed" role="group" aria-label="Simulation speed">
          <span className="hike-note">Simulated walk</span>
          {SPEEDS.map((speed) => (
            <button
              key={speed}
              type="button"
              className={`trail-3d-button${recording.simulation?.speed === speed ? " is-active" : ""}`}
              aria-pressed={recording.simulation?.speed === speed}
              onClick={() => hike.setSimSpeed(speed)}
            >
              {speed}×
            </button>
          ))}
        </div>
      )}

      {status === "running" && (
        <p className="hike-note is-phone">
          Keep the screen on. iPhone web apps can't track with the screen locked.
          {(wakeLock === "unavailable" || wakeLock === "refused") &&
            " This browser won't keep the screen awake, so set auto-lock to Never while you track."}
        </p>
      )}

      <dl className="hike-stats">
        <Stat label="Moving" value={clock(stats.movingMs)} hint={`Elapsed less stops of ${TRACKING.stopMinMs / 60_000} min or more`} />
        {progress && <Stat label="Pace" value={pace(stats.paceMinPerMi)} />}
        <Stat label="Elevation" value={feetOrDash(stats.elevationM)} hint="From the terrain model at your position, smoothed" />
        <Stat label="Gain" value={gainFeet(stats.gainM)} hint={`Smoothed over ${TRACKING.elevationWindowM} m, ${TRACKING.elevationThresholdM} m threshold`} />
        {stats.stops > 0 && <Stat label="Stops" value={String(stats.stops)} />}
      </dl>

      {progress && (
        <section className="hike-trail" aria-label="On the trail">
          <p>
            {miles(progress.leftM)} left · ETA {duration(progress.etaMinutes)}{" "}
            <span className="hike-basis">
              {progress.etaBasis === "pace" ? "at your pace" : "by Naismith's rule, until your pace is known"}
            </span>
          </p>
          {progress.ahead.length > 0 ? (
            <ol className="hike-ahead" aria-label="Next places to camp">
              {progress.ahead.map(({ stop, aheadM }) => (
                <li key={stop.id} className={stop.kind === "candidate" ? "is-candidate" : undefined}>
                  <span>{stop.label}</span>
                  <span className="hike-ahead-mile">{miles(aheadM)}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="hike-note">No campsites ahead on this trail.</p>
          )}
        </section>
      )}

      {farNote && <p className="hike-note is-info">{farNote} Tracking anyway.</p>}
      {hike.problem && <p className="hike-note is-info">{hike.problem}</p>}
      {recording.dropped > 0 && (
        <p className="hike-note">
          {recording.dropped} imprecise fix{recording.dropped === 1 ? "" : "es"} ignored (worse than ±{TRACKING.maxAccuracyM} m).
        </p>
      )}

    </Sheet>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="hike-stat" title={hint}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function Finish({ hike, signedIn, defaultName }: { hike: Hike; signedIn: boolean; defaultName: string }) {
  const [name, setName] = useState(defaultName);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setState("saving");
    setError(null);
    try {
      await hike.save(name.trim() || defaultName);
      setState("saved");
    } catch (caught) {
      setError((caught as Error).message);
      setState("idle");
    }
  };
  return (
    <form
      className="hike-finish"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <label className="hike-name">
        <span>Name</span>
        <input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} />
      </label>
      <div className="hike-controls">
        {signedIn ? (
          <button type="submit" className="button-primary" disabled={state === "saving"}>
            {state === "saving" ? "Saving…" : "Save"}
          </button>
        ) : (
          <Link className="button-primary" to="/login">
            Sign in to save
          </Link>
        )}
        <button
          type="button"
          className="trail-3d-button"
          onClick={() => {
            if (window.confirm("Discard this hike? It hasn't been saved.")) void hike.discard();
          }}
        >
          Discard
        </button>
      </div>
      <p className="hike-note">
        {signedIn
          ? "Saved hikes are in Profile → Hikes. Only this track is sent, once."
          : "The hike stays on this device until you save or discard it."}
      </p>
      {error && <p className="hike-warn">{error}</p>}
    </form>
  );
}

/** The recorded track on the map, above the trails and under the dot. */
function useBreadcrumb(map: maplibregl.Map | null, lines: [number, number][][] | null) {
  const data = useMemo<GeoJSON.Feature>(
    () => ({
      type: "Feature",
      properties: {},
      geometry: { type: "MultiLineString", coordinates: lines ?? [] },
    }),
    [lines],
  );
  useEffect(() => {
    if (!map) return;
    const source = map.getSource(SOURCE) as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    } else if (map.isStyleLoaded()) {
      map.addSource(SOURCE, { type: "geojson", data });
      map.addLayer({
        id: LINE,
        type: "line",
        source: SOURCE,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": token("--hike-track"),
          "line-width": Number(token("--hike-track-width")),
          "line-opacity": Number(token("--hike-track-opacity")),
        },
      });
    }
  }, [map, data]);
}
