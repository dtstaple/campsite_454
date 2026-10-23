/**
 * Trail mode (TM05-111): where the hiker is along the trail they started, and what is
 * ahead. Pure, so node --test checks it.
 *
 *   mile        how far along the trail, in the direction they are walking it: a hike
 *               that starts nearer the far end is walking it end to start
 *   miles left  the rest of the trail in that direction
 *   ETA         the hiker's own moving pace over what is left, once there is enough of a
 *               walk to measure it; until then Naismith's rule over the remaining
 *               distance and climb, as the trail panel estimates the whole trail
 *   ahead       the next mapped campsites and potential spots by trail distance
 *   off trail   farther than offTrailWarnM from the line
 */

import { haversineM, locate, measure, pointAt, type LngLat, type MeasuredLine } from "../trails/geometry.ts";
import { naismithMinutes } from "../trails/format.ts";
import { TRACKING, type TrackingConfig } from "./config.ts";
import { thresholdGain } from "./elevation.ts";

/** A place to camp along the trail, at its distance from the trail's start. */
export interface StopAlong {
  id: string;
  label: string;
  kind: "campsite" | "candidate";
  alongM: number;
}

/** What a trail-mode hike keeps of its trail: enough to work out progress offline. */
export interface TrailSnapshot {
  /** The trail's source_id, as the trail panel keys it. */
  key: string;
  name: string;
  osmId: number | null;
  fromWay: string | null;
  coords: LngLat[];
  profile: { distances: number[]; elevations: number[] } | null;
  stops: StopAlong[];
}

export interface TrailProgress {
  /** Along the trail in the walking direction. */
  doneM: number;
  totalM: number;
  leftM: number;
  offM: number;
  offTrail: boolean;
  etaMinutes: number;
  etaBasis: "pace" | "naismith";
  ahead: { stop: StopAlong; aheadM: number }[];
}

const lines = new WeakMap<LngLat[], MeasuredLine>();

/** The trail line, measured once per snapshot. */
export function trailLine(trail: TrailSnapshot): MeasuredLine {
  let line = lines.get(trail.coords);
  if (!line) {
    line = measure(trail.coords);
    lines.set(trail.coords, line);
  }
  return line;
}

/** Which way a hike starting at `position` walks the trail: from the nearer end. */
export function directionFrom(line: MeasuredLine, position: LngLat): 1 | -1 {
  return locate(line, position) <= line.length / 2 ? 1 : -1;
}

/** How far a position is from the trail, and whether the nearest point is a trailhead. */
export function distanceToTrail(
  line: MeasuredLine,
  position: LngLat,
  config: TrackingConfig = TRACKING,
): { offM: number; atTrailhead: boolean } {
  const alongM = locate(line, position);
  return {
    offM: haversineM(pointAt(line, alongM), position),
    atTrailhead: alongM <= config.trailheadM || alongM >= line.length - config.trailheadM,
  };
}

/** "You're 2.1 mi from the trailhead", or null when the hiker is near enough to start. */
export function farFromTrailNote(
  line: MeasuredLine,
  position: LngLat,
  config: TrackingConfig = TRACKING,
): string | null {
  const { offM, atTrailhead } = distanceToTrail(line, position, config);
  if (offM <= config.farFromTrailM) return null;
  return `You're ${(offM / 1609.344).toFixed(1)} mi from the ${atTrailhead ? "trailhead" : "trail"}.`;
}

/** Climb left on the profile from `alongM` in the walking direction (3 m threshold). */
export function gainLeft(
  profile: TrailSnapshot["profile"],
  alongM: number,
  direction: 1 | -1,
  thresholdM = TRACKING.elevationThresholdM,
): number {
  if (!profile || profile.distances.length === 0) return 0;
  const values: number[] = [];
  profile.distances.forEach((d, i) => {
    if (direction === 1 ? d >= alongM : d <= alongM) values.push(profile.elevations[i]);
  });
  return thresholdGain(direction === 1 ? values : values.reverse(), thresholdM);
}

export function trailProgress(
  trail: TrailSnapshot,
  position: LngLat,
  direction: 1 | -1,
  walked: { distanceM: number; movingMs: number },
  config: TrackingConfig = TRACKING,
  aheadCount = 3,
): TrailProgress {
  const line = trailLine(trail);
  const alongM = locate(line, position);
  const offM = haversineM(pointAt(line, alongM), position);
  const doneM = direction === 1 ? alongM : line.length - alongM;
  const leftM = Math.max(0, line.length - doneM);

  const usePace = walked.distanceM >= config.paceMinM && walked.movingMs >= config.paceMinMs;
  const etaMinutes = usePace
    ? (leftM * (walked.movingMs / walked.distanceM)) / 60_000
    : naismithMinutes(leftM, gainLeft(trail.profile, alongM, direction, config.elevationThresholdM));

  const ahead = trail.stops
    .map((stop) => ({ stop, aheadM: (stop.alongM - alongM) * direction }))
    .filter((entry) => entry.aheadM > 0)
    .sort((a, b) => a.aheadM - b.aheadM)
    .slice(0, aheadCount);

  return {
    doneM,
    totalM: line.length,
    leftM,
    offM,
    offTrail: offM > config.offTrailWarnM,
    etaMinutes,
    etaBasis: usePace ? "pace" : "naismith",
    ahead,
  };
}

const M_PER_MI = 1609.344;

/** "2.3 of 7.4 mi", "1.5 of 137 mi": the unit once, at the end (TM05-138). A trail of
 * 100 mi or more drops the total's decimal, so the value stays short on a phone. */
export function mileOf(progress: Pick<TrailProgress, "doneM" | "totalM">): string {
  const total = progress.totalM / M_PER_MI;
  const totalText = total >= 100 ? total.toFixed(0) : total.toFixed(1);
  return `${(progress.doneM / M_PER_MI).toFixed(1)} of ${totalText} mi`;
}
