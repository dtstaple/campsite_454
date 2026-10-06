/**
 * The score in the campsite panel (TM05-47): the total first, in its grade colour, then
 * each factor with its sub-score and what was measured. All of the deciding is in
 * score/breakdown.ts; this only lays it out.
 */

import type { CSSProperties } from "react";
import { breakdownView, type FactorRow } from "../score/breakdown";
import { gradeToken } from "../score/grade";

interface Props {
  /** The contract-1 score (docs/scoring.md), if the selection carried one. */
  breakdown: unknown;
  /** A bare total from the map or a trail list, for when there is no breakdown. */
  total: number | null;
}

export default function ScoreBreakdown({ breakdown, total }: Props) {
  const view = breakdownView(breakdown, total);

  if (view.kind === "none") {
    return (
      <section className="campsite-score" aria-label="Score">
        <div className="campsite-score-note">No score yet</div>
      </section>
    );
  }

  return (
    <section className="campsite-score" aria-label="Score">
      <div className="campsite-score-total" style={{ "--score-color": `var(${gradeToken(view.grade)})` } as CSSProperties}>
        <span className="campsite-score-number">{view.score}</span>
        <span className="campsite-score-of">/ 100</span>
        <span className="campsite-score-grade">{view.grade}</span>
      </div>

      {view.kind === "total-only" && <div className="campsite-score-note">Breakdown pending</div>}

      {view.kind === "scored" && (
        <>
          {view.caps.map((reason) => (
            <div key={reason} className="campsite-score-cap">
              {reason}
            </div>
          ))}
          <ul className="campsite-factors">
            {view.rows.map((row) => (
              <FactorItem key={row.key} row={row} />
            ))}
          </ul>
          {view.missing > 0 && (
            <div className="campsite-score-note">
              {view.missing === 1 ? "1 factor is" : `${view.missing} factors are`} not available and left out
              of the total, not counted as 0.
            </div>
          )}
        </>
      )}
    </section>
  );
}

function FactorItem({ row }: { row: FactorRow }) {
  const missing = row.status === "not_available";
  return (
    <li className={`campsite-factor${missing ? " is-missing" : ""}`}>
      <span className="campsite-factor-label">{row.label}</span>
      <span
        className="campsite-factor-value"
        style={{ "--score-color": `var(${gradeToken(row.grade)})` } as CSSProperties}
      >
        {row.value}
      </span>
      <span className="campsite-factor-detail">{row.detail}</span>
    </li>
  );
}
