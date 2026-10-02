/**
 * Compact floating segmented control for the activity mode.
 *
 * Renders ENABLED_MODES only, so a mode switched off in modes.ts cannot appear here.
 */

import { ModeIcon } from "./icons";
import { ENABLED_MODES, type ModeId } from "./modes";

interface Props {
  active: ModeId;
  onChange: (id: ModeId) => void;
}

export default function ModeSwitcher({ active, onChange }: Props) {
  return (
    <div className="mode-switcher" role="radiogroup" aria-label="Activity">
      {ENABLED_MODES.map((mode) => {
        const isActive = mode.id === active;
        return (
          <button
            key={mode.id}
            type="button"
            role="radio"
            aria-checked={isActive}
            className={`mode-button${isActive ? " is-active" : ""}`}
            onClick={() => onChange(mode.id)}
          >
            <ModeIcon icon={mode.icon} />
            <span>{mode.label}</span>
          </button>
        );
      })}
    </div>
  );
}
