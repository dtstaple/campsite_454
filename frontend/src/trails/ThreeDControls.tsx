/**
 * 3D controls under the elevation chart (TM05-62): the terrain toggle, play/pause for the
 * flythrough, and a one-line hint about scrubbing.
 */

interface Props {
  is3D: boolean;
  playing: boolean;
  reducedMotion: boolean;
  onToggle3D: () => void;
  onPlay: () => void;
  onPause: () => void;
}

export default function ThreeDControls({
  is3D,
  playing,
  reducedMotion,
  onToggle3D,
  onPlay,
  onPause,
}: Props) {
  return (
    <div className="trail-3d">
      <button
        type="button"
        className={`trail-3d-button${is3D ? " is-active" : ""}`}
        aria-pressed={is3D}
        onClick={onToggle3D}
      >
        3D
      </button>
      <button
        type="button"
        className="trail-3d-button"
        onClick={playing ? onPause : onPlay}
        aria-label={playing ? "Pause flythrough" : "Play flythrough"}
        title={reducedMotion ? "Reduced motion is on: the flythrough steps instead of gliding" : undefined}
      >
        {playing ? "❚❚ Pause" : "▶ Fly the trail"}
      </button>
      <span className="trail-3d-hint">
        {is3D ? "Drag the profile to move along the trail" : "Turn on 3D to see the terrain"}
      </span>
    </div>
  );
}
