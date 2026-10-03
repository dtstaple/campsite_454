/**
 * Feature ids that survive MapLibre (TM05-63).
 *
 * The map API sets every GeoJSON Feature's `id` to its `source_id` -- "node/5759412256",
 * "way/1305981156", "campsite/104324" (docs/api.md). MapLibre's GeoJSON sources only keep
 * numeric feature ids: a string like "node/5759412256" does not survive into the features
 * that queryRenderedFeatures hands back, which report id 0 instead. Reading `feature.id`
 * in the popup therefore sent POST /api/saved-campsites/0/ -> 404 -> "Could not save that
 * campsite." for every campsite on the map.
 *
 * So the id travels as a property instead, which MapLibre keeps verbatim: copy it in
 * before setData(), read it back with sourceIdOf().
 */

import type { Feature, FeatureCollection } from "geojson";

export const SOURCE_ID_PROPERTY = "source_id";

/** The collection with each feature's `id` also stored as `properties.source_id`. */
export function withSourceIds<T extends FeatureCollection>(collection: T): T {
  return {
    ...collection,
    features: collection.features.map((feature) =>
      feature.id === undefined || feature.id === null
        ? feature
        : {
            ...feature,
            properties: { ...feature.properties, [SOURCE_ID_PROPERTY]: String(feature.id) },
          },
    ),
  };
}

/**
 * The source_id of a feature as MapLibre returns it from a click. Only the property is
 * trusted: `feature.id` from MapLibre is a number at best, so it is never used.
 */
export function sourceIdOf(feature: Pick<Feature, "properties">): string {
  const value = feature.properties?.[SOURCE_ID_PROPERTY];
  return typeof value === "string" ? value : "";
}
