/**
 * A shared overnight plan (TM05-172), opened from a share link: /shared/<token>.
 *
 * No sign-in. It shows the route (a strip from start to end with each night's stop placed
 * by distance), the nights, and each day's distance, gain and loss, read-only. The API
 * sends nothing about the plan's owner, so there is nothing here to hide.
 */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getSharedPlan, type SharedPlan as Plan } from "../plans/api";
import { nights } from "../plans/draft";
import { stripMarks } from "../plans/share";
import { feet, miles } from "../trails/format";
import "../plans/plans.css";

export default function SharedPlan() {
  const { token = "" } = useParams();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getSharedPlan(token)
      .then((answer) => live && setPlan(answer))
      .catch((error: Error) => live && setProblem(error.message));
    return () => {
      live = false;
    };
  }, [token]);

  return (
    <main className="page shared-plan-page">
      <article className="shared-plan" aria-label="Shared overnight plan">
        {problem && (
          <p className="plan-problem" role="alert">
            {problem}
          </p>
        )}
        {!plan && !problem && <p className="plan-hint">Loading the plan…</p>}
        {plan && <PlanBody plan={plan} />}
      </article>
    </main>
  );
}

function PlanBody({ plan }: { plan: Plan }) {
  const marks = stripMarks(plan.trail.length_m, plan.stops);
  return (
    <>
      <div className="panel-subtitle">Shared overnight plan · read-only</div>
      <h1 className="shared-plan-title">{plan.name}</h1>
      <p className="shared-plan-trail">
        {plan.trail.name} · {miles(plan.trail.length_m)} · {nights(plan.nights)}
      </p>

      <section aria-label="Route">
        <ol className="shared-plan-strip">
          <li className="shared-plan-end" style={{ left: "0%" }}>
            Start
          </li>
          {marks.map((mark) => (
            <li
              key={mark.night}
              className="shared-plan-stop"
              style={{ left: `${mark.percent}%` }}
              title={`Night ${mark.night}: ${mark.label}`}
            >
              {mark.night}
            </li>
          ))}
          <li className="shared-plan-end is-end" style={{ left: "100%" }}>
            End
          </li>
        </ol>
        <ol className="shared-plan-stops">
          {plan.stops.map((stop) => (
            <li key={stop.night}>
              <span className="shared-plan-night">Night {stop.night}</span>{" "}
              {stop.display_name ?? "Campsite"} · {miles(stop.distance_along_m)} in
              <span className={`plan-verdict is-${stop.legality.verdict}`}>
                {stop.legality.label}
              </span>
            </li>
          ))}
        </ol>
      </section>

      {plan.warnings.length > 0 && (
        <ul className="plan-warnings" aria-label="Stops to check">
          {plan.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <table className="plan-days">
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col">To</th>
            <th scope="col">Distance</th>
            <th scope="col">Gain</th>
            <th scope="col">Loss</th>
          </tr>
        </thead>
        <tbody>
          {plan.days.map((day) => (
            <tr key={day.day}>
              <td>{day.day}</td>
              <td>
                <span className="plan-to">{day.to}</span>
              </td>
              <td>{miles(day.distance_m)}</td>
              <td>{day.gain_m === null ? "—" : feet(day.gain_m)}</td>
              <td>{day.loss_m === null ? "—" : feet(day.loss_m)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" colSpan={2}>
              {nights(plan.nights)}
            </th>
            <td>{miles(plan.totals.distance_m)}</td>
            <td>{plan.totals.gain_m === null ? "—" : feet(plan.totals.gain_m)}</td>
            <td>{plan.totals.loss_m === null ? "—" : feet(plan.totals.loss_m)}</td>
          </tr>
        </tfoot>
      </table>
      {plan.profile.status !== "ok" && (
        <p className="plan-hint">Elevation is unavailable, so the days show distance only.</p>
      )}
      <p className="plan-hint">In the trail's own direction, start to end.</p>
    </>
  );
}
