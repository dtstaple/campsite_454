/**
 * Comparing trails side by side (TM05-121): the list behind the comparison tray. Up to
 * three trails, added from the trail panel or a Discover card. Pure, so node --test checks
 * adding, removing and the limit.
 *
 * Each entry is a snapshot of the facts the API already returned (the route detail or the
 * Discover card data, docs/api.md), so the tray needs no request of its own.
 */

import type { RouteDetail, RouteHit } from "./api";
import type { TrailTarget } from "../profile/openRequest";
import { DIFFICULTY_LABELS, ROUTE_TYPE_LABELS, campsitesLine } from "./cards.ts";
import { duration, feet, miles, naismithMinutes } from "./format.ts";

export const COMPARE_MAX = 3;

export interface ComparedTrail {
  /** The trail's identity: "relation/123", or "assembled/way/456" for an assembled trail. */
  key: string;
  target: TrailTarget;
  name: string;
  length_m: number;
  /** Null until the route's profile has been computed. */
  gain_m: number | null;
  difficulty: keyof typeof DIFFICULTY_LABELS | null;
  route_type: keyof typeof ROUTE_TYPE_LABELS | null;
  route_type_estimated: boolean;
  campsites: number;
  campsites_within_m: number;
}

export type AddResult =
  | { status: "added"; list: ComparedTrail[] }
  | { status: "already"; list: ComparedTrail[] }
  | { status: "full"; list: ComparedTrail[] };

export function isCompared(list: readonly ComparedTrail[], key: string): boolean {
  return list.some((trail) => trail.key === key);
}

export function isFull(list: readonly ComparedTrail[]): boolean {
  return list.length >= COMPARE_MAX;
}

/** Add a trail at the end. A fourth is refused, not swapped in: the hiker chooses what goes. */
export function addTrail(list: readonly ComparedTrail[], trail: ComparedTrail): AddResult {
  if (isCompared(list, trail.key)) return { status: "already", list: [...list] };
  if (isFull(list)) return { status: "full", list: [...list] };
  return { status: "added", list: [...list, trail] };
}

export function removeTrail(list: readonly ComparedTrail[], key: string): ComparedTrail[] {
  return list.filter((trail) => trail.key !== key);
}

/** A Discover card's trail (TM05-102 card data). */
export function fromHit(hit: RouteHit): ComparedTrail {
  return {
    key: `relation/${hit.osm_id}`,
    target: { osmId: hit.osm_id },
    name: hit.name,
    length_m: hit.length_m,
    gain_m: hit.gain_m,
    difficulty: hit.difficulty ?? null,
    route_type: hit.route_type ?? null,
    route_type_estimated: Boolean(hit.route_type_estimated),
    campsites: hit.campsites ?? 0,
    campsites_within_m: hit.campsites_within_m ?? 500,
  };
}

/**
 * The trail open in the panel. Null for a route planned across trails (TM05-119), which is
 * not one trail and can't be reopened as one.
 */
export function fromDetail(detail: RouteDetail): ComparedTrail | null {
  if (detail.planned) return null;
  const target: TrailTarget | null =
    detail.osm_id !== null ? { osmId: detail.osm_id } : detail.assembly ? { wayId: detail.assembly.from_way } : null;
  if (!target) return null;
  return {
    key: detail.source_id,
    target,
    name: detail.name,
    length_m: detail.length_m,
    gain_m: detail.profile.status === "ok" ? detail.profile.stats.gain_m : null,
    difficulty: detail.difficulty?.rating ?? null,
    route_type: detail.route_type?.type ?? null,
    route_type_estimated: detail.route_type?.estimated ?? false,
    campsites: detail.campsites.count,
    campsites_within_m: detail.campsites.within_m,
  };
}

/** The tray's rows, one value per trail, in the order the trails were added. */
export function compareRows(list: readonly ComparedTrail[]): { label: string; values: string[] }[] {
  const notMeasured = "Not measured yet";
  return [
    { label: "Distance", values: list.map((t) => miles(t.length_m)) },
    { label: "Gain", values: list.map((t) => (t.gain_m === null ? notMeasured : feet(t.gain_m))) },
    { label: "Difficulty", values: list.map((t) => (t.difficulty ? DIFFICULTY_LABELS[t.difficulty] : "—")) },
    {
      label: "Route type",
      values: list.map((t) =>
        t.route_type ? ROUTE_TYPE_LABELS[t.route_type] + (t.route_type_estimated && t.route_type !== "loop" ? " (est.)" : "") : "—",
      ),
    },
    {
      label: "Est. time",
      values: list.map((t) => (t.gain_m === null ? notMeasured : duration(naismithMinutes(t.length_m, t.gain_m)))),
    },
    { label: "Campsites", values: list.map((t) => campsitesLine(t)) },
  ];
}

/** Read the list back from storage, defensively: it is whatever was written, by any version. */
export function parseCompared(raw: string | null): ComparedTrail[] {
  if (!raw) return [];
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(value)) return [];
  const valid = value.filter(
    (item): item is ComparedTrail =>
      Boolean(item) &&
      typeof item.key === "string" &&
      typeof item.name === "string" &&
      Number.isFinite(item.length_m) &&
      Boolean(item.target) &&
      (Number.isFinite(item.target.osmId) || typeof item.target.wayId === "string"),
  );
  return valid.filter((item, i) => valid.findIndex((other) => other.key === item.key) === i).slice(0, COMPARE_MAX);
}
