/**
 * The hike panel's glance row (TM05-111, fixed in TM05-138): elapsed time, distance, and
 * either the trail progress or the pace. Pure, so node --test checks what the panel shows:
 * each value carries its unit once, however long the trail.
 */

import { clock, miles2, pace } from "./format.ts";
import { mileOf, type TrailProgress } from "./progress.ts";

export interface GlanceItem {
  label: string;
  value: string;
}

export function glanceItems(
  stats: { elapsedMs: number; distanceM: number; paceMinPerMi: number | null },
  progress: Pick<TrailProgress, "doneM" | "totalM"> | null,
): GlanceItem[] {
  return [
    { label: "Elapsed", value: clock(stats.elapsedMs) },
    { label: "Distance", value: miles2(stats.distanceM) },
    progress
      ? { label: "Trail", value: mileOf(progress) }
      : { label: "Pace", value: pace(stats.paceMinPerMi) },
  ];
}
