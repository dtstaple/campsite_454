/**
 * "Describe your trip" on Discover trails (TM05-170). The sentence goes to the server,
 * which reads it into the filters CampSite supports; the page then searches with those
 * filters exactly as if they had been set in the Filters panel. "How I read your request"
 * shows them as chips: remove one with ×, or choose it to edit it in the Filters panel.
 */

import { useRef, useState } from "react";
import type { TrailFilters } from "../trails/filters";
import { interpretTrip } from "./tripApi";
import {
  chipsFor,
  fallbackNote,
  unsupportedLine,
  withoutChip,
  type Extras,
  type InterpretAnswer,
} from "./tripReading";

interface Props {
  filters: TrailFilters;
  extras: Extras;
  regionLabel: string | null;
  /** A new reading: its filters, extras and region replace the page's. */
  onAnswer: (answer: InterpretAnswer) => void;
  onChange: (filters: TrailFilters, extras: Extras) => void;
  onEdit: () => void;
}

export default function TripFinder({ filters, extras, regionLabel, onAnswer, onChange, onEdit }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [answer, setAnswer] = useState<InterpretAnswer | null>(null);
  const pending = useRef<AbortController | null>(null);

  const submit = async () => {
    if (!text.trim()) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setProblem(null);
    try {
      const read = await interpretTrip(text, controller.signal);
      setAnswer(read);
      onAnswer(read);
    } catch (error) {
      if ((error as Error).name !== "AbortError") setProblem((error as Error).message);
    } finally {
      if (pending.current === controller) setBusy(false);
    }
  };

  const chips = answer ? chipsFor(filters, extras, regionLabel) : [];
  const note = answer ? fallbackNote(answer) : null;

  return (
    <section className="trip-finder" aria-label="Describe your trip">
      <form
        className="trip-finder-form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="trip-finder-label" htmlFor="trip-finder-text">
          Describe your trip
        </label>
        <div className="trip-finder-row">
          <input
            id="trip-finder-text"
            type="text"
            enterKeyHint="search"
            autoComplete="off"
            maxLength={300}
            placeholder="e.g. two nights, lakeside, moderate climb"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <button type="submit" className="button-primary" disabled={busy || !text.trim()}>
            {busy ? "Reading…" : "Find trips"}
          </button>
        </div>
      </form>

      {problem && (
        <p className="trip-finder-problem" role="alert">
          {problem}
        </p>
      )}

      {answer && (
        <div className="trip-finder-reading" role="status">
          <div className="trip-finder-title">How I read your request</div>
          {chips.length === 0 && !answer.interpretation.unsupported.length && (
            <p className="trip-finder-note">
              Nothing here maps to a filter yet. Try a length, a climb, nights or a region.
            </p>
          )}
          {chips.length > 0 && (
            <ul className="trip-chips">
              {chips.map((chip) => (
                <li key={chip.key} className={`trip-chip is-${chip.kind}`} title={chip.note}>
                  <button
                    type="button"
                    className="trip-chip-label"
                    onClick={onEdit}
                    aria-label={`${chip.label}: edit in Filters`}
                  >
                    {chip.label}
                    {chip.note && <span className="trip-chip-note">{chip.note}</span>}
                  </button>
                  {chip.key !== "region" && (
                    <button
                      type="button"
                      className="trip-chip-remove"
                      aria-label={`Remove ${chip.label}`}
                      onClick={() => {
                        const next = withoutChip(chip.key, filters, extras);
                        onChange(next.filters, next.extras);
                      }}
                    >
                      ×
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {answer.interpretation.unsupported.length > 0 && (
            <ul className="trip-unsupported" aria-label="Not measured yet">
              {answer.interpretation.unsupported.map((ask) => (
                <li key={ask}>{unsupportedLine(ask)}</li>
              ))}
            </ul>
          )}
          {note && <p className="trip-finder-note">{note}</p>}
        </div>
      )}
    </section>
  );
}
