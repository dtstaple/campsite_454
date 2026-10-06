/**
 * The score colour system (TM05-48): letter grades over the contract-1 score, 0-100
 * (docs/scoring.md). Why grades and not v1's gradient is measured in theme.css.
 *
 * The bands are the one place a score becomes a grade. The map paint, the legend and the
 * campsite panel all read them from here, so they cannot disagree. Pure: no DOM, so the
 * colours are passed in (theme.ts reads them) and node --test can load this file.
 */

export type GradeLetter = "A" | "B" | "C" | "D" | "F";

/** Highest first. A score is the first grade whose `min` it reaches. */
export const GRADES: readonly { letter: GradeLetter; min: number }[] = [
  { letter: "A", min: 90 },
  { letter: "B", min: 80 },
  { letter: "C", min: 70 },
  { letter: "D", min: 60 },
  { letter: "F", min: 0 },
];

/** A real score: a finite number. null, a string or NaN is "no score", never 0. */
export function isScore(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** The grade for a score, or null when there is no score. */
export function gradeFor(score: unknown): GradeLetter | null {
  if (!isScore(score)) return null;
  return GRADES.find((grade) => score >= grade.min)?.letter ?? "F";
}

/** "A 90+", "F < 60": the band as the legend writes it. */
export function bandLabel(letter: GradeLetter): string {
  const index = GRADES.findIndex((grade) => grade.letter === letter);
  return letter === "F" ? `F < ${GRADES[index - 1].min}` : `${letter} ${GRADES[index].min}+`;
}

/** The CSS custom property for a grade, or for "no score". */
export function gradeToken(letter: GradeLetter | null): string {
  return letter ? `--score-${letter.toLowerCase()}` : "--score-none";
}

export type ScoreColors = Record<GradeLetter, string> & { none: string };

/**
 * MapLibre `circle-color` for the campsite markers: a step over the feature's `score`
 * property. Anything that is not a number -- a missing property, null, a string -- takes
 * the neutral colour, so an unscored site is never drawn as an F.
 */
export function scoreColorExpression(colors: ScoreColors): unknown[] {
  const ascending = [...GRADES].reverse(); // F, D, C, B, A
  const steps: unknown[] = [colors[ascending[0].letter]];
  for (const grade of ascending.slice(1)) steps.push(grade.min, colors[grade.letter]);
  return [
    "case",
    ["==", ["typeof", ["get", "score"]], "number"],
    ["step", ["get", "score"], ...steps],
    colors.none,
  ];
}
