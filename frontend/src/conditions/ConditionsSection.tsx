/**
 * The Conditions section of the trail and campsite panels (TM05-120): active NWS alerts
 * first, highlighted, then a three-day forecast, each with its source and fetch time.
 * Fetched when the section mounts for a point; the server caches both briefly, so
 * reopening a panel does not call the weather services again.
 */

import { useEffect, useState } from "react";
import { ConditionsApiError, fetchConditions } from "./api";
import {
  alertTone,
  alertUntil,
  dayLabel,
  precipitationText,
  sourceText,
  temperatureText,
  windText,
  type AlertsSection,
  type Conditions,
  type ForecastSection,
  type LatLon,
} from "./conditions";
import "./conditions.css";

type State = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; conditions: Conditions };

interface Props {
  point: LatLon;
  /** Where the point is, when it is not obvious: "Midway along the trail". */
  note?: string;
}

export default function ConditionsSection({ point, note }: Props) {
  const { lat, lon } = point;
  const key = `${lat},${lon}`;
  const [loaded, setLoaded] = useState<{ key: string; state: State } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchConditions({ lat, lon }, controller.signal)
      .then((conditions) => setLoaded({ key, state: { status: "ready", conditions } }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        const message = error instanceof ConditionsApiError ? error.message : String(error);
        setLoaded({ key, state: { status: "error", message } });
      });
    return () => controller.abort();
  }, [key, lat, lon]);

  // Until this point's answer arrives, show loading rather than the previous point's.
  const state: State = loaded?.key === key ? loaded.state : { status: "loading" };

  return (
    <section className="conditions" aria-label="Conditions">
      <div className="panel-subtitle">Conditions</div>
      {note && <p className="conditions-note">{note}</p>}
      {state.status === "loading" && <p className="conditions-status">Loading the forecast…</p>}
      {state.status === "error" && (
        <p className="conditions-status is-error">Conditions are unavailable right now ({state.message}).</p>
      )}
      {state.status === "ready" && (
        <>
          <Alerts section={state.conditions.alerts} />
          <Forecast section={state.conditions.forecast} />
        </>
      )}
    </section>
  );
}

function Alerts({ section }: { section: AlertsSection }) {
  return (
    <div className="conditions-block">
      {section.status === "error" ? (
        <p className="conditions-status is-error">{section.message}</p>
      ) : section.items.length === 0 ? (
        <p className="conditions-status">No active weather alerts.</p>
      ) : (
        <ul className="conditions-alerts">
          {section.items.map((alert) => (
            <li key={alert.id} className={`conditions-alert is-${alertTone(alert.severity)}`}>
              <details>
                <summary>
                  <span className="conditions-alert-event">{alert.event}</span>
                  {alertUntil(alert) && <span className="conditions-sub">{alertUntil(alert)}</span>}
                </summary>
                {alert.headline && <p>{alert.headline}</p>}
                {alert.instruction && <p>{alert.instruction}</p>}
                {alert.description && <p className="conditions-alert-text">{alert.description}</p>}
              </details>
            </li>
          ))}
        </ul>
      )}
      <p className="conditions-source">Alerts: {sourceText(section)}</p>
    </div>
  );
}

function Forecast({ section }: { section: ForecastSection }) {
  return (
    <div className="conditions-block">
      {section.status === "error" ? (
        <p className="conditions-status is-error">{section.message}</p>
      ) : section.days.length === 0 ? (
        <p className="conditions-status">No forecast for here.</p>
      ) : (
        <ol className="conditions-days">
          {section.days.map((day, index) => (
            <li key={day.date} className="conditions-day">
              <span className="conditions-day-name">{dayLabel(day.date, index)}</span>
              <span className="conditions-day-temp">{temperatureText(day)}</span>
              <span className="conditions-sub">{precipitationText(day)}</span>
              {windText(day) && <span className="conditions-sub">{windText(day)}</span>}
            </li>
          ))}
        </ol>
      )}
      <p className="conditions-source">Forecast: {sourceText(section)}</p>
    </div>
  );
}
