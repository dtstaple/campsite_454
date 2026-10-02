/**
 * Lookups on a profile's distance/elevation series, shared by the chart, the panel and the
 * 3D camera.
 */

/** Index of the sample nearest `distance` (distances ascending). */
export function nearestIndex(distances: number[], distance: number): number {
  let lo = 0;
  let hi = distances.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (distances[mid] <= distance) lo = mid;
    else hi = mid;
  }
  return distance - distances[lo] <= distances[hi] - distance ? lo : hi;
}

/** Grade in percent around sample `index`, over about `windowM` metres. */
export function gradeAt(distances: number[], elevations: number[], index: number, windowM = 100) {
  const target = distances[index];
  const a = nearestIndex(distances, target - windowM / 2);
  const b = nearestIndex(distances, target + windowM / 2);
  const run = distances[b] - distances[a];
  return run > 0 ? ((elevations[b] - elevations[a]) / run) * 100 : 0;
}
