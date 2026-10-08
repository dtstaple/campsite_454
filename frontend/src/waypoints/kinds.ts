/**
 * The four waypoint kinds (TM05-80) and how each is drawn. Pure, so node --test can load
 * it. The kinds match planning.models.Waypoint.Kind on the server.
 */

export type WaypointKind = "water" | "camp" | "bailout" | "custom";

export interface KindStyle {
  id: WaypointKind;
  label: string;
  /** The theme.css colour token for the marker. */
  token: string;
  /** SVG path data, drawn in a 16x16 box, white on the colour. */
  glyph: string;
}

export const KINDS: readonly KindStyle[] = [
  {
    id: "water",
    label: "Water",
    token: "--waypoint-water",
    glyph: "M8 1.5C8 1.5 3.5 7 3.5 10a4.5 4.5 0 0 0 9 0C12.5 7 8 1.5 8 1.5Z",
  },
  {
    id: "camp",
    label: "Camp",
    token: "--waypoint-camp",
    glyph: "M8 2 1.5 13.5h13L8 2Zm0 5.2 3 6.3H5l3-6.3Z",
  },
  {
    id: "bailout",
    label: "Bail-out",
    token: "--waypoint-bailout",
    glyph: "M9 2.5 14.5 8 9 13.5v-3.5H2V6h7V2.5Z",
  },
  {
    id: "custom",
    label: "Custom",
    token: "--waypoint-custom",
    glyph: "M3.5 1.5h1.6v1h7.4l-1.8 3 1.8 3H5.1v6H3.5v-13Z",
  },
];

export function kindStyle(kind: string): KindStyle {
  return KINDS.find((entry) => entry.id === kind) ?? KINDS[KINDS.length - 1];
}

export const NAME_MAX = 80;
export const NOTE_MAX = 2000;

/** Why a draft can't be saved, or null when it can. Mirrors the server's checks. */
export function draftError(draft: { name: string; note: string }): string | null {
  const name = draft.name.trim();
  if (!name) return "Give the waypoint a name.";
  if (name.length > NAME_MAX) return `Keep the name under ${NAME_MAX} characters.`;
  if (draft.note.length > NOTE_MAX) return `Keep the note under ${NOTE_MAX} characters.`;
  return null;
}

/** A starting name for a new waypoint, so a quick drop saves in one click. */
export function defaultName(kind: WaypointKind, existing: readonly { name: string }[]): string {
  const base = kindStyle(kind).label;
  const taken = new Set(existing.map((w) => w.name));
  if (!taken.has(base)) return base;
  for (let n = 2; ; n++) if (!taken.has(`${base} ${n}`)) return `${base} ${n}`;
}
