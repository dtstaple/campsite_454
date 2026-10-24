/**
 * The Profile's scoring preferences (TM05-115): one slider per factor over the saved
 * weights of TM05-46. Contract: docs/api.md, "Scoring weights". Pure, so node --test
 * checks load, save, reset and the all-zero guard.
 *
 * A slider runs 0-100 and stands for the weight times 100, so the shipped 0.35 for water
 * reads 35. Weights are relative (the engine renormalises), so only the proportions
 * matter; the server rejects all zero, and setWeight() never produces it.
 */

export const FACTORS = [
  { key: "water", label: "Close to water", hint: "Distance to a stream, river or lake" },
  { key: "legal", label: "Legal to camp", hint: "Whether the land allows camping" },
  { key: "trail", label: "Near a trail", hint: "Distance to the nearest trail" },
  { key: "weather", label: "Good weather", hint: "Today's forecast at the site" },
  { key: "slope", label: "Flat ground", hint: "How level the terrain is" },
  { key: "land_cover", label: "Land cover", hint: "Forest, meadow or open ground" },
  // TM05-143: from the terrain model (make terrain).
  { key: "drainage", label: "Drains well", hint: "Low water pooling risk in rain" },
  { key: "shelter", label: "Sheltered", hint: "Lower than the ground around it, out of the wind" },
  { key: "view", label: "A view", hint: "How much you can see, and water in view" },
] as const;

export type FactorKey = (typeof FACTORS)[number]["key"];
/** Slider positions, 0-100, one per factor. */
export type Sliders = Record<FactorKey, number>;

export const SLIDER_MAX = 100;

/** GET/PUT /api/auth/me/weights/. */
export interface WeightsPayload {
  weights: Record<string, number>;
  defaults: Record<string, number>;
  custom: boolean;
}

function clamp(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(SLIDER_MAX, Math.max(0, Math.round(value)));
}

/** Slider positions for a weights object; a factor it lacks falls back to `fallback`. */
export function toSliders(weights: Record<string, number>, fallback: Record<string, number> = {}): Sliders {
  const sliders = {} as Sliders;
  for (const { key } of FACTORS) sliders[key] = clamp((weights[key] ?? fallback[key] ?? 0) * SLIDER_MAX);
  return sliders;
}

/** The PUT body for these slider positions. */
export function toRequest(sliders: Sliders): { weights: Record<FactorKey, number> } {
  const weights = {} as Record<FactorKey, number>;
  for (const { key } of FACTORS) weights[key] = sliders[key] / SLIDER_MAX;
  return { weights };
}

export function allZero(sliders: Sliders): boolean {
  return FACTORS.every(({ key }) => sliders[key] === 0);
}

/**
 * Move one slider. If every other factor is already at zero, this one cannot go below 1:
 * the sliders can never reach the all-zero state the server rejects.
 */
export function setWeight(sliders: Sliders, key: FactorKey, value: number): Sliders {
  const othersZero = FACTORS.every((factor) => factor.key === key || sliders[factor.key] === 0);
  return { ...sliders, [key]: othersZero ? Math.max(1, clamp(value)) : clamp(value) };
}

/** Each factor's share of the score, in whole percent, for the label beside a slider. */
export function shares(sliders: Sliders): Sliders {
  const total = FACTORS.reduce((sum, { key }) => sum + sliders[key], 0);
  const result = {} as Sliders;
  for (const { key } of FACTORS) result[key] = total ? Math.round((sliders[key] / total) * 100) : 0;
  return result;
}

export function sameSliders(a: Sliders, b: Sliders): boolean {
  return FACTORS.every(({ key }) => a[key] === b[key]);
}

/** The section is for a signed-in user only: the weights belong to an account. */
export function showPreferences(session: { token: string } | null): boolean {
  return session !== null;
}
