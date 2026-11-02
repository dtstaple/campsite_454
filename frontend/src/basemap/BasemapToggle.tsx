/**
 * Floating standard / satellite switch (TM05-65). Shown in every activity mode.
 *
 * TM05-144: the map's other view controls (the 3D button) ride in the same pill as
 * `children`, so they share its position above the attribution and above an open sheet.
 */

import type { ReactNode } from "react";
import type { Basemap } from "./useBasemap";
import "./basemap.css";

const OPTIONS: { id: Basemap; label: string }[] = [
  { id: "standard", label: "Map" },
  { id: "satellite", label: "Satellite" },
];

interface Props {
  value: Basemap;
  onChange: (next: Basemap) => void;
  children?: ReactNode;
}

export default function BasemapToggle({ value, onChange, children }: Props) {
  return (
    <div className="basemap-toggle">
      <div className="basemap-options" role="radiogroup" aria-label="Basemap">
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
      {children && <div className="basemap-extra">{children}</div>}
    </div>
  );
}
