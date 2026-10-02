/**
 * Mode icons. Drawn for this project as plain strokes on a 20px grid, in currentColor so
 * they take the button's text colour.
 */

import type { ModeIconId } from "./modes";

const PATHS: Record<ModeIconId, string> = {
  // A ridge line with a switchback trail climbing it.
  hiking: "M2 16 L7.5 7 L10.5 11 L13 8 L18 16 M7 16 L9 13.5 L8 12 L10.5 10.5",
  // A tent: ridge, door and guy lines.
  camping: "M3 16 L10 4 L17 16 Z M10 16 L10 10.5 L12.5 16 M1.5 16 L18.5 16",
  // Two crossed skis over a slope.
  ski: "M3 5 L15 17 M17 5 L5 17 M2 15 Q10 9 18 13",
};

export function ModeIcon({ icon }: { icon: ModeIconId }) {
  return (
    <svg
      className="mode-icon"
      viewBox="0 0 20 20"
      width="16"
      height="16"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d={PATHS[icon]}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
