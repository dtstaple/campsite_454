/**
 * Compare trails side by side (TM05-121). "Compare" on the trail panel or a Discover card
 * adds a trail (CompareButton); the header's "Compare (n)" opens this tray over the page.
 * Columns on desktop, stacked cards on a phone (compare.css). Choosing a column opens that
 * trail on the map, as a Discover card does.
 */

import type { CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { COMPARE_MAX, compareRows, isCompared, isFull, type ComparedTrail } from "./compare";
import { addCompared, clearCompared, removeCompared, useCompared } from "./compareStore";
import { OPEN_STATE_KEY, type OpenRequest } from "../profile/openRequest";
import "./trails.css";
import "./compare.css";

export function CompareButton({ trail }: { trail: ComparedTrail | null }) {
  const list = useCompared();
  if (!trail) return null;
  const compared = isCompared(list, trail.key);
  const full = !compared && isFull(list);
  return (
    <button
      type="button"
      className={`trail-3d-button compare-button${compared ? " is-active" : ""}`}
      aria-pressed={compared}
      disabled={full}
      title={full ? `You can compare up to ${COMPARE_MAX} trails. Remove one first.` : undefined}
      onClick={() => (compared ? removeCompared(trail.key) : addCompared(trail))}
    >
      {compared ? "Comparing" : "Compare"}
    </button>
  );
}

/** The header's toggle; hidden while nothing is being compared. */
export function CompareToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const list = useCompared();
  if (list.length === 0) return null;
  return (
    <button
      type="button"
      className={`nav-link compare-toggle${open ? " active" : ""}`}
      aria-expanded={open}
      aria-controls="compare-tray"
      onClick={onToggle}
    >
      Compare ({list.length})
    </button>
  );
}

export default function CompareTray({ open, onClose }: { open: boolean; onClose: () => void }) {
  const list = useCompared();
  const navigate = useNavigate();
  if (!open || list.length === 0) return null;

  const rows = compareRows(list);
  const openOnMap = (trail: ComparedTrail) => {
    const request: OpenRequest = { kind: "trail", trail: trail.target, name: trail.name };
    onClose();
    navigate("/discover", { state: { [OPEN_STATE_KEY]: request } });
  };

  return (
    <section id="compare-tray" className="compare-tray" aria-label="Compare trails">
      <header className="compare-head">
        <h2>Compare trails</h2>
        <span className="compare-hint">
          {list.length} of {COMPARE_MAX} · choose one to open it on the map
        </span>
        <button type="button" className="link-button" onClick={clearCompared}>
          Clear
        </button>
        <button type="button" className="trail-close" onClick={onClose} aria-label="Close comparison">
          ×
        </button>
      </header>
      <ol className="compare-columns" style={{ "--compare-count": list.length } as CSSProperties}>
        {list.map((trail, i) => (
          <li key={trail.key} className="compare-column">
            <button type="button" className="compare-open" onClick={() => openOnMap(trail)}>
              <span className="compare-name">{trail.name}</span>
              {rows.map((row) => (
                <span key={row.label} className="compare-row">
                  <span className="compare-label">{row.label}</span>
                  <span className="compare-value">{row.values[i]}</span>
                </span>
              ))}
            </button>
            <button
              type="button"
              className="link-button compare-remove"
              onClick={() => removeCompared(trail.key)}
              aria-label={`Remove ${trail.name} from the comparison`}
            >
              Remove
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
