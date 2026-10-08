/**
 * "Overnight plan" in the trail panel (TM05-81): the campsites chosen as stops (with the
 * Night buttons in the campsite list below), each day's distance, gain and loss, the
 * legality of every stop, and saving, reopening, deleting and exporting plans.
 *
 * The numbers are the server's: every change to the stops asks /api/plans/preview/, which
 * orders the stops along the route and measures each day on the route's stored profile.
 * TrailInsight owns the draft so the campsite rows and this section share it.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { Session } from "../auth";
import type { RouteDetail } from "../trails/api";
import { feet, miles } from "../trails/format";
import {
  createPlan,
  deletePlan,
  downloadPlanGpx,
  getPlan,
  listPlans,
  previewPlan,
  updatePlan,
  type PlanSummary,
  type WorkedPlan,
} from "./api";
import { nights, planFilename, trailRef, type PlanDraft } from "./draft";
import "./plans.css";

interface Props {
  detail: RouteDetail;
  session: Session | null;
  draft: PlanDraft;
  onDraft: (draft: PlanDraft) => void;
  /** The worked-out plan, for the Night numbers in the campsite list. */
  onWorked?: (plan: WorkedPlan | null) => void;
}

const PREVIEW_DELAY_MS = 250;

export default function PlanBuilder({ detail, session, draft, onDraft, onWorked }: Props) {
  const trail = trailRef(detail);
  const trailQuery = trail ? JSON.stringify(trail) : null;
  const [worked, setWorked] = useState<WorkedPlan | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState<PlanSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  // --- the plans already saved for this trail --------------------------------------------
  const [listVersion, setListVersion] = useState(0);
  useEffect(() => {
    if (!session || !trailQuery) return;
    let cancelled = false;
    listPlans(session, JSON.parse(trailQuery))
      .then((plans) => !cancelled && setSaved(plans))
      .catch(() => !cancelled && setSaved([]));
    return () => {
      cancelled = true;
    };
  }, [session, trailQuery, listVersion]);

  // --- preview whenever the stops change ----------------------------------------------------
  const stopKey = draft.stopIds.join("|");
  useEffect(() => {
    if (!session || !trailQuery || !stopKey) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      previewPlan(session, JSON.parse(trailQuery), stopKey.split("|"))
        .then((plan) => {
          if (cancelled) return;
          setWorked(plan);
          setProblem(null);
          onWorked?.(plan);
        })
        .catch((error: Error) => {
          if (cancelled) return;
          setWorked(null);
          setProblem(error.message);
          onWorked?.(null);
        });
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [session, trailQuery, stopKey, onWorked]);

  const shown = stopKey ? worked : null;

  if (!trail) return null;
  if (!session) {
    return (
      <section className="plan" aria-label="Overnight plan">
        <div className="panel-subtitle">Overnight plan</div>
        <p className="plan-hint">
          <Link to="/login">Sign in</Link> to choose campsites as overnight stops and see each
          day's distance and climb.
        </p>
      </section>
    );
  }

  const save = async () => {
    setBusy(true);
    setStatus(null);
    try {
      const plan =
        draft.planId === null
          ? await createPlan(session, trail, draft.stopIds, draft.name)
          : await updatePlan(session, draft.planId, draft.stopIds, draft.name);
      onDraft({ ...draft, planId: plan.id, name: plan.name });
      setStatus(draft.planId === null ? "Plan saved." : "Plan updated.");
      setListVersion((v) => v + 1);
    } catch (error) {
      setProblem((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const open = async (id: number) => {
    setBusy(true);
    setStatus(null);
    try {
      const plan = await getPlan(session, id);
      onDraft({
        trailKey: draft.trailKey,
        planId: plan.id,
        name: plan.name,
        stopIds: plan.stops.map((stop) => stop.id),
      });
    } catch (error) {
      setProblem((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    if (confirmDelete !== id) {
      setConfirmDelete(id);
      return;
    }
    setConfirmDelete(null);
    try {
      await deletePlan(session, id);
      if (draft.planId === id) onDraft({ ...draft, planId: null });
      setListVersion((v) => v + 1);
    } catch (error) {
      setProblem((error as Error).message);
    }
  };

  const download = async () => {
    if (draft.planId === null) return;
    try {
      await downloadPlanGpx(session, draft.planId, planFilename(draft.name));
    } catch (error) {
      setProblem((error as Error).message);
    }
  };

  return (
    <section className="plan" aria-label="Overnight plan">
      <div className="plan-head">
        <div className="panel-subtitle">Overnight plan</div>
        {draft.stopIds.length > 0 && (
          <button
            type="button"
            className="plan-link"
            onClick={() => onDraft({ ...draft, stopIds: [], planId: null, name: "" })}
          >
            New plan
          </button>
        )}
      </div>

      {draft.stopIds.length === 0 && (
        <p className="plan-hint">
          Choose <b>+ Night</b> beside campsites in the list below to stop there overnight.
        </p>
      )}

      {problem && draft.stopIds.length > 0 && (
        <p className="plan-problem" role="alert">
          {problem}
        </p>
      )}

      {shown && (
        <>
          {shown.warnings.length > 0 && (
            <ul className="plan-warnings" aria-label="Stops to check">
              {shown.warnings.map((warning) => (
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
              {shown.days.map((day) => {
                const stop = shown.stops[day.day - 1];
                return (
                  <tr key={day.day}>
                    <td>{day.day}</td>
                    <td>
                      <span className="plan-to">{day.to}</span>
                      {stop && (
                        <span className={`plan-verdict is-${stop.legality.verdict}`}>
                          {stop.legality.label}
                        </span>
                      )}
                    </td>
                    <td>{miles(day.distance_m)}</td>
                    <td>{day.gain_m === null ? "—" : feet(day.gain_m)}</td>
                    <td>{day.loss_m === null ? "—" : feet(day.loss_m)}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={2}>
                  {nights(shown.nights)}
                </th>
                <td>{miles(shown.totals.distance_m)}</td>
                <td>{shown.totals.gain_m === null ? "—" : feet(shown.totals.gain_m)}</td>
                <td>{shown.totals.loss_m === null ? "—" : feet(shown.totals.loss_m)}</td>
              </tr>
            </tfoot>
          </table>
          {shown.profile.status !== "ok" && (
            <p className="plan-hint">Elevation is unavailable, so the days show distance only.</p>
          )}
          <p className="plan-hint">
            In the trail's own direction, start to end. Gain and loss are measured like the
            trail's, per day.
          </p>

          <form
            className="plan-save"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <input
              aria-label="Plan name"
              placeholder={`${detail.name}: ${nights(shown.nights)}`}
              value={draft.name}
              maxLength={120}
              onChange={(event) => onDraft({ ...draft, name: event.target.value })}
            />
            <button type="submit" className="button-primary" disabled={busy}>
              {draft.planId === null ? "Save plan" : "Update"}
            </button>
          </form>
          {draft.planId !== null && (
            <button type="button" className="trail-3d-button" onClick={() => void download()}>
              Download plan GPX
            </button>
          )}
          {status && (
            <p className="plan-status" role="status">
              {status}
            </p>
          )}
        </>
      )}

      {saved.length > 0 && (
        <div className="plan-saved">
          <div className="plan-saved-title">Your plans for this trail</div>
          <ul>
            {saved.map((plan) => (
              <li key={plan.id} className={plan.id === draft.planId ? "is-open" : undefined}>
                <button
                  type="button"
                  className="plan-saved-open"
                  disabled={busy}
                  onClick={() => void open(plan.id)}
                >
                  {plan.name}
                  <span>{nights(plan.nights ?? 0)}</span>
                </button>
                <button
                  type="button"
                  className="plan-saved-delete"
                  onClick={() => void remove(plan.id)}
                >
                  {confirmDelete === plan.id ? "Really delete?" : "Delete"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
