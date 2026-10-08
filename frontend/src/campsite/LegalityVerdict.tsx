/**
 * "Permitted · designated site", "Not permitted", or "Unknown: check current rules",
 * above the score (TM05-76 follow-up). The reason, and the NYS DEC rule it rests on with a
 * link to the source, sit underneath.
 */

import type { Legality } from "./legality";

export default function LegalityVerdict({ legality }: { legality: Legality }) {
  return (
    <section className={`campsite-verdict is-${legality.verdict}`} aria-label="Camping legality">
      <div className="campsite-verdict-label">{legality.label}</div>
      <p className="campsite-verdict-reason">{legality.reason}</p>
      {legality.rule && (
        <p className="campsite-verdict-rule">
          “{legality.rule.text}”{" "}
          <a href={legality.rule.source} target="_blank" rel="noopener noreferrer">
            NYS DEC
          </a>
        </p>
      )}
    </section>
  );
}
