/**
 * The legality verdict above the score (TM05-76 follow-up), and the score without its
 * legal factor: legality is a verdict, not one weighted factor among the others.
 */

export type Verdict = "permitted" | "not_permitted" | "unknown";

export interface Legality {
  verdict: Verdict;
  label: string;
  reason: string;
  rule: { text: string; source: string } | null;
  designated: boolean;
  designation_basis: string | null;
  elevation_ft: number | null;
}

/**
 * A contract-1 score with the `legal` factor taken out of its factor list, for the
 * breakdown under the verdict. Accepts the object or its JSON string (map feature
 * properties arrive as strings); anything else is returned unchanged for the breakdown's
 * own parser to judge. The total is untouched: it is the score the API gave.
 */
export function withoutLegalFactor(raw: unknown): unknown {
  let value = raw;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return raw;
    }
  }
  if (typeof value !== "object" || value === null || !Array.isArray((value as { factors?: unknown }).factors)) {
    return raw;
  }
  const score = value as { factors: { key?: unknown }[] };
  return { ...score, factors: score.factors.filter((factor) => factor?.key !== "legal") };
}
