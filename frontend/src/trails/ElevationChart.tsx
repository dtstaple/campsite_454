/**
 * Elevation profile as plain SVG (TM05-61): no chart library, because one area chart with
 * a cursor is a few dozen lines and a dependency is not.
 *
 * Controlled: the parent owns `cursorM` (metres along the route) so the map and the chart
 * can drive each other. Pointer movement over the chart reports a distance through
 * `onHover`; pressing and dragging reports it through `onScrub` as well, which the 3D
 * camera follows (TM05-62).
 */

import { useRef } from "react";
import { nearestIndex } from "./profile";

const WIDTH = 320;
const HEIGHT = 132;
const PAD = { top: 10, right: 6, bottom: 18, left: 6 };

export interface ChartMarker {
  distance: number;
  label: string;
}

interface Props {
  distances: number[];
  elevations: number[];
  cursorM: number | null;
  markers?: ChartMarker[];
  onHover: (distance: number | null) => void;
  onScrub?: (distance: number) => void;
  formatDistance: (metres: number) => string;
  formatHeight: (metres: number) => string;
}

export default function ElevationChart({
  distances,
  elevations,
  cursorM,
  markers = [],
  onHover,
  onScrub,
  formatDistance,
  formatHeight,
}: Props) {
  const svg = useRef<SVGSVGElement>(null);
  const dragging = useRef(false);

  const length = distances[distances.length - 1] || 1;
  const low = Math.min(...elevations);
  const high = Math.max(...elevations);
  // Never draw a near-flat route as a cliff: give the vertical axis at least 50 m.
  const span = Math.max(high - low, 50);
  const innerW = WIDTH - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const x = (d: number) => PAD.left + (d / length) * innerW;
  const y = (e: number) => PAD.top + innerH - ((e - low) / span) * innerH;

  const line = distances.map((d, i) => `${i ? "L" : "M"}${x(d).toFixed(1)},${y(elevations[i]).toFixed(1)}`).join("");
  const area = `${line}L${x(length).toFixed(1)},${PAD.top + innerH}L${x(0).toFixed(1)},${PAD.top + innerH}Z`;

  const distanceAt = (clientX: number) => {
    const rect = svg.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return 0;
    const svgX = ((clientX - rect.left) / rect.width) * WIDTH;
    return Math.max(0, Math.min(length, ((svgX - PAD.left) / innerW) * length));
  };

  const cursorIndex =
    cursorM === null ? -1 : nearestIndex(distances, Math.max(0, Math.min(length, cursorM)));

  return (
    <svg
      ref={svg}
      className="elevation-chart"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={`Elevation profile, ${formatHeight(low)} to ${formatHeight(high)}`}
      onPointerMove={(event) => {
        const d = distanceAt(event.clientX);
        onHover(d);
        if (dragging.current) onScrub?.(d);
      }}
      onPointerLeave={() => {
        if (!dragging.current) onHover(null);
      }}
      onPointerDown={(event) => {
        dragging.current = true;
        event.currentTarget.setPointerCapture(event.pointerId);
        onScrub?.(distanceAt(event.clientX));
      }}
      onPointerUp={(event) => {
        dragging.current = false;
        event.currentTarget.releasePointerCapture(event.pointerId);
      }}
    >
      <line className="chart-grid" x1={PAD.left} x2={WIDTH - PAD.right} y1={y(high)} y2={y(high)} />
      <line className="chart-grid" x1={PAD.left} x2={WIDTH - PAD.right} y1={y(low)} y2={y(low)} />
      <path className="chart-area" d={area} />
      <path className="chart-line" d={line} />

      {markers.map((marker) => (
        <line
          key={`${marker.label}-${marker.distance}`}
          className="chart-marker"
          x1={x(marker.distance)}
          x2={x(marker.distance)}
          y1={PAD.top + innerH}
          y2={PAD.top + innerH - 6}
        >
          <title>{marker.label}</title>
        </line>
      ))}

      <text className="chart-label" x={PAD.left} y={HEIGHT - 4}>
        0
      </text>
      <text className="chart-label" x={WIDTH - PAD.right} y={HEIGHT - 4} textAnchor="end">
        {formatDistance(length)}
      </text>
      <text className="chart-label" x={PAD.left + 2} y={y(high) + 11}>
        {formatHeight(high)}
      </text>

      {cursorIndex >= 0 && (
        <g className="chart-cursor">
          <line x1={x(distances[cursorIndex])} x2={x(distances[cursorIndex])} y1={PAD.top} y2={PAD.top + innerH} />
          <circle cx={x(distances[cursorIndex])} cy={y(elevations[cursorIndex])} r={3.5} />
        </g>
      )}
    </svg>
  );
}
