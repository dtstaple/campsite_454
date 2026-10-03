/**
 * Floating standard / satellite switch (TM05-65). Shown in every activity mode.
 */

import type { Basemap } from "./useBasemap";
import "./basemap.css";

const OPTIONS: { id: Basemap; label: string }[] = [
  { id: "standard", label: "Map" },
  { id: "satellite", label: "Satellite" },
];

interface Props {
  value: Basemap;
  onChange: (next: Basemap) => void;
}

export default function BasemapToggle({ value, onChange }: Props) {
  return (
    <div className="basemap-toggle" role="radiogroup" aria-label="Basemap">
      {OPTIONS.map((option) => (
        <button
          key={option.id}
          type="button"
          role="radio"
          aria-checked={value === option.id}
          className={`basemap-button${value === option.id ? " is-active" : ""}`}
          onClick={() => onChange(option.id)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
