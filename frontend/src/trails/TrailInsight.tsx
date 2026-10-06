/**
 * Trail insight (TM05-61): named routes on the map, and the trail panel for the one the
 * user clicks.
 *
 * Self-contained so the map page only has to mount it: given the map, it adds its own
 * sources and layers (mapLayers.ts), fetches routes for the viewport, owns the selected
 * route's detail, and keeps the chart cursor and the map marker in step. Hovering the
 * chart moves the marker along the route; hovering the route moves the chart cursor.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { Feature, FeatureCollection, Point } from "geojson";
import { clampBbox, type Bbox } from "../api";
import { fetchRouteDetail, fetchRoutes, RouteApiError, type CampsiteAlong } from "./api";
import { locate, measure, pointAt, type LngLat, type MeasuredLine } from "./geometry";
import {
  addRouteLayers,
  ALONG_SOURCE,
  EMPTY,
  removeRouteLayers,
  ROUTES_HIT,
  ROUTES_SOURCE,
  SELECTED_HIT,
  SELECTED_SOURCE,
} from "./mapLayers";
import TrailPanel, { type DetailState } from "./TrailPanel";
import ThreeDControls from "./ThreeDControls";
import { CAMERA, easeBearing, rigFor } from "./camera";
import { disable3D, enable3D, prefersReducedMotion } from "./terrain3d";
import type { CampsiteSelection } from "../campsite/selection";
import "./trails.css";

/** Below this zoom a route list would be most of a region; skip the request. */
const MIN_ROUTE_ZOOM = 9;
const DEBOUNCE_MS = 400;
const DEFAULT_WITHIN_M = 500;
/** Flythrough speed bounds, metres per second: a short trail still takes a while, a long
 * one does not take all day. Aim for about 45 s end to end in between. */
const FLY_MIN_MPS = 60;
const FLY_MAX_MPS = 400;
const FLY_TARGET_S = 45;
/** With reduced motion the flythrough steps rather than glides. */
const REDUCED_STEP_M = 500;
const REDUCED_STEP_MS = 1500;

interface Props {
  map: maplibregl.Map | null;
  /** Select a campsite (TM05-66, TM05-69). Without it, a click just flies there. */
  onOpenCampsite?: (selection: CampsiteSelection) => void;
  /** A campsite row is hovered (TM05-69): its source_id, or null. */
  onHoverCampsite?: (sourceId: string | null) => void;
}

export default function TrailInsight({ map, onOpenCampsite, onHoverCampsite }: Props) {
  const [selected, setSelected] = useState<{ osmId: number; name: string } | null>(null);
  const [state, setState] = useState<DetailState | null>(null);
  const [cursorM, setCursorM] = useState<number | null>(null);
  const [withinM, setWithinM] = useState(DEFAULT_WITHIN_M);

  const line = useMemo<MeasuredLine | null>(
    () =>
      state?.status === "ready" ? measure(state.detail.line.coordinates as LngLat[]) : null,
    [state],
  );
  // Map handlers are registered once; they read the current line through a ref.
  const lineRef = useRef(line);
  useEffect(() => {
    lineRef.current = line;
  }, [line]);

  // --- 3D: terrain, scrubber camera, flythrough ----------------------------------------

  const [is3D, setIs3D] = useState(false);
  const [playing, setPlaying] = useState(false);
  const previousMaxPitch = useRef<number | null>(null);
  const rig = useMemo(() => (line ? rigFor(line) : null), [line]);
  const cursorRef = useRef(cursorM);
  useEffect(() => {
    cursorRef.current = cursorM;
  }, [cursorM]);

  /** Put the camera behind and above `distance`, easing its bearing by `easing` (0-1). */
  const placeCamera = useCallback(
    (distance: number, easing: number) => {
      if (!map || !rig) return;
      const camera = rig.at(distance);
      map.jumpTo({
        center: camera.center,
        bearing: easeBearing(map.getBearing(), camera.bearing, easing),
        pitch: CAMERA.pitch,
        zoom: CAMERA.zoom,
      });
    },
    [map, rig],
  );

  const turn3DOn = useCallback(() => {
    if (!map) return;
    previousMaxPitch.current = enable3D(map);
    setIs3D(true);
    placeCamera(cursorRef.current ?? 0, 1);
  }, [map, placeCamera]);

  const turn3DOff = useCallback(() => {
    setPlaying(false);
    if (map) disable3D(map, previousMaxPitch.current ?? 60);
    setIs3D(false);
  }, [map]);

  const scrub = useCallback(
    (distance: number) => {
      setCursorM(distance);
      if (is3D) placeCamera(distance, 0.5);
    },
    [is3D, placeCamera],
  );

  const play = useCallback(() => {
    if (!is3D) turn3DOn();
    setPlaying(true);
  }, [is3D, turn3DOn]);

  useEffect(() => {
    if (!playing || !map || !line) return;
    let distance = cursorRef.current ?? 0;
    if (distance >= line.length - 1) distance = 0;
    const speed = Math.min(FLY_MAX_MPS, Math.max(FLY_MIN_MPS, line.length / FLY_TARGET_S));
    const stop = () => setPlaying(false);
    // Grabbing the map is a clear "I'll take it from here".
    map.on("dragstart", stop);

    let frame = 0;
    let timer: number | undefined;
    if (prefersReducedMotion()) {
      const step = () => {
        distance = Math.min(line.length, distance + REDUCED_STEP_M);
        setCursorM(distance);
        placeCamera(distance, 1);
        if (distance >= line.length) stop();
        else timer = window.setTimeout(step, REDUCED_STEP_MS);
      };
      timer = window.setTimeout(step, 0);
    } else {
      let last = performance.now();
      const tick = (now: number) => {
        const dt = Math.min(0.1, (now - last) / 1000);
        last = now;
        distance = Math.min(line.length, distance + speed * dt);
        setCursorM(distance);
        // Ease the bearing a little each frame so turns are turns, not cuts.
        placeCamera(distance, Math.min(1, dt * 2.5));
        if (distance >= line.length) stop();
        else frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    }
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(timer);
      map.off("dragstart", stop);
    };
  }, [playing, map, line, placeCamera]);

  // --- layers and viewport routes ----------------------------------------------------

  useEffect(() => {
    if (!map) return;
    addRouteLayers(map);

    let controller: AbortController | null = null;
    let timer: number | undefined;
    const load = () => {
      controller?.abort();
      const source = map.getSource(ROUTES_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (map.getZoom() < MIN_ROUTE_ZOOM) {
        source?.setData(EMPTY);
        return;
      }
      controller = new AbortController();
      const bbox = clampBbox(map.getBounds().toArray().flat() as Bbox);
      fetchRoutes(bbox, controller.signal)
        .then((routes) => source?.setData(routes as unknown as FeatureCollection))
        .catch(() => {
          /* routes are context; a failed refresh leaves the previous ones drawn */
        });
    };
    const onMove = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(load, DEBOUNCE_MS);
    };

    const onRouteClick = (event: maplibregl.MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      const osmId = Number(feature?.properties?.osm_id);
      if (!osmId) return;
      const name = String(feature?.properties?.name ?? "Trail");
      // Loading is set here, from the event, rather than in the fetching effect.
      setState((previous) =>
        previous?.status === "ready" && previous.detail.osm_id === osmId
          ? previous
          : { status: "loading", name },
      );
      setSelected({ osmId, name });
    };
    const onRouteHover = () => {
      map.getCanvas().style.cursor = "pointer";
    };
    const onSelectedHover = (event: maplibregl.MapLayerMouseEvent) => {
      const current = lineRef.current;
      if (current) setCursorM(locate(current, [event.lngLat.lng, event.lngLat.lat]));
    };
    const onSelectedLeave = () => setCursorM(null);

    map.on("moveend", onMove);
    map.on("click", ROUTES_HIT, onRouteClick);
    map.on("mousemove", ROUTES_HIT, onRouteHover);
    map.on("mousemove", SELECTED_HIT, onSelectedHover);
    map.on("mouseleave", SELECTED_HIT, onSelectedLeave);
    load();

    return () => {
      window.clearTimeout(timer);
      controller?.abort();
      map.off("moveend", onMove);
      map.off("click", ROUTES_HIT, onRouteClick);
      map.off("mousemove", ROUTES_HIT, onRouteHover);
      map.off("mousemove", SELECTED_HIT, onSelectedHover);
      map.off("mouseleave", SELECTED_HIT, onSelectedLeave);
      // On unmount the page may already have removed the map; its layers went with it.
      try {
        removeRouteLayers(map);
      } catch {
        /* map already removed */
      }
    };
  }, [map]);

  // --- the selected route's detail ----------------------------------------------------

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    fetchRouteDetail(selected.osmId, withinM, controller.signal)
      .then((detail) => setState({ status: "ready", detail }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          name: selected.name,
          message: error instanceof RouteApiError ? error.message : String(error),
        });
      });
    return () => controller.abort();
  }, [selected, withinM]);

  // Frame the route once when it first loads, leaving room for the panel on the right.
  const framed = useRef<number | null>(null);
  useEffect(() => {
    if (!map || state?.status !== "ready") return;
    const { detail } = state;
    (map.getSource(SELECTED_SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData({
      type: "Feature",
      properties: {},
      geometry: detail.line,
    });
    const points: Feature<Point>[] = detail.campsites.items.map((site) => ({
      type: "Feature",
      properties: { id: site.id },
      geometry: { type: "Point", coordinates: [site.lon, site.lat] },
    }));
    (map.getSource(ALONG_SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: points,
    });
    if (framed.current !== detail.osm_id) {
      framed.current = detail.osm_id;
      const bounds = new maplibregl.LngLatBounds();
      for (const coordinate of detail.line.coordinates) bounds.extend(coordinate as LngLat);
      map.fitBounds(bounds, { padding: { top: 60, bottom: 60, left: 280, right: 400 }, maxZoom: 14 });
    }
  }, [map, state]);

  // --- cursor marker -----------------------------------------------------------------

  const marker = useRef<maplibregl.Marker | null>(null);
  useEffect(() => {
    if (!map) return;
    if (cursorM === null || !line) {
      marker.current?.remove();
      marker.current = null;
      return;
    }
    if (!marker.current) {
      const element = document.createElement("div");
      element.className = "trail-cursor-marker";
      marker.current = new maplibregl.Marker({ element });
    }
    marker.current.setLngLat(pointAt(line, cursorM)).addTo(map);
  }, [map, line, cursorM]);

  // --- closing -------------------------------------------------------------------------

  const close = useCallback(() => {
    if (is3D) turn3DOff();
    onHoverCampsite?.(null);
    setSelected(null);
    setState(null);
    setCursorM(null);
    framed.current = null;
    (map?.getSource(SELECTED_SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData(EMPTY);
    (map?.getSource(ALONG_SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData(EMPTY);
  }, [map, is3D, turn3DOff, onHoverCampsite]);

  useEffect(() => {
    if (!selected) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, close]);

  const showCampsite = useCallback(
    (site: CampsiteAlong) => {
      setCursorM(site.distance_along_m);
      if (onOpenCampsite) {
        onOpenCampsite({ id: site.id, lon: site.lon, lat: site.lat, name: site.name, score: site.score });
      }
      else map?.flyTo({ center: [site.lon, site.lat], zoom: Math.max(map.getZoom(), 14) });
    },
    [map, onOpenCampsite],
  );

  if (!state) return null;
  return (
    <TrailPanel
      state={state}
      cursorM={cursorM}
      withinM={withinM}
      onCursor={setCursorM}
      onScrub={scrub}
      onWithin={setWithinM}
      onCampsite={showCampsite}
      onCampsiteHover={(site) => onHoverCampsite?.(site ? site.id : null)}
      onClose={close}
      controls={
        <ThreeDControls
          is3D={is3D}
          playing={playing}
          reducedMotion={prefersReducedMotion()}
          onToggle3D={is3D ? turn3DOff : turn3DOn}
          onPlay={play}
          onPause={() => setPlaying(false)}
        />
      }
    />
  );
}
