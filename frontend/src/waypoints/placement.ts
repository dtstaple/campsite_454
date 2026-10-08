/**
 * Whether the next map click places a waypoint (TM05-80). Shared with Discover's map click
 * handler, which must not open a popup or the trail panel for the click that drops a
 * waypoint. A module-level flag rather than React state, because the handler is
 * registered once when the map is created.
 */
export const placement = { active: false };
