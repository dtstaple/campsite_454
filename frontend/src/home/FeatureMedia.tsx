/**
 * A screen recording in a fixed 16:10 frame (TM05-68), for the homepage.
 *
 * The frame's size never depends on what is inside it, so nothing moves when a video
 * arrives, fails, or is still being checked. Inside it, in order:
 *
 *   - nothing, until the frame is within a screen of the viewport (lazy);
 *   - the video, once a request shows the file really is a video;
 *   - otherwise a placeholder that says exactly what to record (docs/media-shot-list.md).
 *
 * The check matters because a missing file under public/ does not 404 in dev or on most
 * static hosts: the SPA fallback answers 200 with index.html. So "exists" means "answers
 * with a video/* content type", not "answers 200".
 *
 * Motion: the video autoplays muted and loops, with a pause button, because a loop longer
 * than five seconds needs one (WCAG 2.2.2). With prefers-reduced-motion it does not
 * autoplay; the poster shows with a play button instead.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

interface Props {
  /** Under public/, e.g. "/media/hero.mp4". */
  src: string;
  /** The first frame as a JPEG, e.g. "/media/hero-poster.jpg". */
  poster: string;
  /** What to record, shown in the placeholder until the file exists. */
  label: string;
  /** What the recording shows, for screen readers. */
  description: string;
  /** Above the fold: check straight away rather than waiting to scroll near it. */
  eager?: boolean;
}

type Availability = "unknown" | "video" | "missing";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function subscribeReducedMotion(onChange: () => void) {
  const query = window.matchMedia(REDUCED_MOTION);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia(REDUCED_MOTION).matches,
    () => false,
  );
}

/**
 * Whether `url` answers with a `prefix`* content type. A one-byte ranged GET rather than a
 * HEAD: Vite's dev server answers HEAD for an existing .mp4 with the index.html fallback.
 * Only the headers are wanted, so the body is cancelled as soon as they arrive (servers
 * that ignore the range would otherwise send the whole file).
 */
async function servesType(url: string, prefix: string, signal: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(url, { headers: { Range: "bytes=0-0" }, signal });
    void response.body?.cancel();
    return response.ok && (response.headers.get("content-type") ?? "").startsWith(prefix);
  } catch {
    return false;
  }
}

export default function FeatureMedia({ src, poster, label, description, eager = false }: Props) {
  const frameRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [near, setNear] = useState(eager);
  const [availability, setAvailability] = useState<Availability>("unknown");
  const [hasPoster, setHasPoster] = useState(false);
  const [playing, setPlaying] = useState(false);
  const reducedMotion = usePrefersReducedMotion();

  // Lazy: wait until the frame is within one screen of the viewport.
  useEffect(() => {
    if (near) return;
    const frame = frameRef.current;
    if (!frame) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setNear(true);
      },
      // The page scrolls inside .page, not the window; a margin only reaches past what is
      // on screen when it is measured against the element that actually scrolls.
      { root: frame.closest(".page"), rootMargin: "100% 0px" },
    );
    observer.observe(frame);
    return () => observer.disconnect();
  }, [near]);

  useEffect(() => {
    if (!near) return;
    const controller = new AbortController();
    Promise.all([
      servesType(src, "video/", controller.signal),
      servesType(poster, "image/", controller.signal),
    ]).then(([video, image]) => {
      if (controller.signal.aborted) return;
      setHasPoster(image);
      setAvailability(video ? "video" : "missing");
    });
    return () => controller.abort();
  }, [near, src, poster]);

  // React sets `muted` as a property only after mount, too late for some browsers'
  // autoplay check, so set it on the element directly before asking it to play.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = true;
    video.defaultMuted = true;
    if (reducedMotion) {
      video.pause();
    } else {
      video.play().catch(() => setPlaying(false));
    }
  }, [availability, reducedMotion]);

  function toggle() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.play().catch(() => setPlaying(false));
    } else {
      video.pause();
    }
  }

  return (
    <div ref={frameRef} className="feature-media">
      {availability === "video" && (
        <>
          <video
            ref={videoRef}
            className="feature-media-video"
            src={src}
            poster={hasPoster ? poster : undefined}
            muted
            loop
            playsInline
            preload="none"
            autoPlay={!reducedMotion}
            aria-label={description}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
          />
          <button
            type="button"
            className={`feature-media-toggle${playing ? "" : " is-paused"}`}
            onClick={toggle}
            aria-label={playing ? `Pause: ${description}` : `Play: ${description}`}
          >
            <svg className="feature-media-icon" viewBox="0 0 12 12" aria-hidden="true">
              {playing ? (
                <path d="M2 1h3v10H2zM7 1h3v10H7z" />
              ) : (
                <path d="M2.5 1l8 5-8 5z" />
              )}
            </svg>
            {playing ? "Pause" : "Play"}
          </button>
        </>
      )}
      {availability === "missing" && (
        <div className="feature-media-placeholder" role="img" aria-label={description}>
          <p className="feature-media-label">{label}</p>
          <p className="feature-media-file">{src.replace(/^\//, "public/")}</p>
        </div>
      )}
    </div>
  );
}
