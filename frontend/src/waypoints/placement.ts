/**
 * Whether the next map click places a waypoint (TM05-80), or a route planner stop
 * (TM05-119). Shared with Discover's map click handler, which must not open a popup or the
 * trail panel for that click. A module-level flag rather than React state, because the handler is
 * registered once when the map is created.
 */
export const placement = { active: false };
