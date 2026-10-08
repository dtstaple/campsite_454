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
import {
  fetchCandidates,
  fetchRouteDetail,
  fetchRoutes,
  fetchTrailForWay,
  RouteApiError,
  type CampsiteAlong,
  type RouteHit,
} from "./api";
import TrailSearch from "./TrailSearch";
import { locate, measure, pointAt, type LngLat, type MeasuredLine } from "./geometry";
import {
  addRouteLayers,
  ALONG_SOURCE,
  EMPTY,
  isRouteHit,
  removeRouteLayers,
  ROUTES_HIT,
  ROUTES_SOURCE,
  SELECTED_HIT,
  SELECTED_SOURCE,
} from "./mapLayers";
import TrailPanel, { type DetailState, type Finder } from "./TrailPanel";
import AlongMarkers from "./AlongMarkers";
import { candidatesPath, type Candidate } from "./candidates";
import { connectionTarget, type Junction } from "./connections";
import ThreeDControls from "./ThreeDControls";
import { CAMERA, easeBearing, rigFor } from "./camera";
import { disable3D, enable3D, prefersReducedMotion } from "./terrain3d";
import type { CampsiteSelection } from "../campsite/selection";
import { isAlong, isNamedTrail } from "./format";
import { sourceIdOf } from "../map/featureIds";

/** Trail segments' click layer (map/layers.ts) and the campsite layer that outranks it. */
const TRAIL_SEGMENTS_HIT = "trails-hit";
const CAMPSITES_POINT = "campsites-point";
import { placement } from "../waypoints/placement";
import PlanBuilder from "../plans/PlanBuilder";
import { getPlan } from "../plans/api";
import type { OpenRequest } from "../profile/openRequest";
import type { WorkedPlan } from "../plans/api";
import { draftFor, toggleStop, type PlanDraft } from "../plans/draft";
import { useSession } from "../session";
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
  /** TM05-100: a saved trail or plan to open once, from the Profile page. */
  openRequest?: Extract<OpenRequest, { kind: "trail" | "plan" }> | null;
}

export default function TrailInsight({
  map,
  onOpenCampsite,
  onHoverCampsite,
  openRequest,
}: Props) {
  // A named route by relation id, or (TM05-97) a named trail way, which the API resolves to
  // its route or to a trail assembled from the connected same-name ways.
  const [selected, setSelected] = useState<
    { osmId: number; name: string } | { wayId: string; name: string } | null
  >(null);
  const [state, setState] = useState<DetailState | null>(null);
  const [cursorM, setCursorM] = useState<number | null>(null);
  const [withinM, setWithinM] = useState(DEFAULT_WITHIN_M);

  // TM05-81: the overnight plan being built for the open trail. Kept here so the Night
  // buttons in the campsite list and the plan section share it; keyed by trail, so
  // opening another trail starts empty (plans/draft.ts).
  const { session } = useSession();
  const [planDraft, setPlanDraft] = useState<PlanDraft | null>(null);
  const [worked, setWorked] = useState<WorkedPlan | null>(null);

  // TM05-99: the campsite search, per trail. Nothing along the trail is drawn, and no
  // candidate search runs, until the hiker asks for it.
  const [finding, setFinding] = useState<{ key: string; finder: Finder } | null>(null);
  const [openCandidate, setOpenCandidate] = useState<Candidate | null>(null);
  // TM05-101: the junctions of the connecting trail under the pointer.
  const [hoveredJunctions, setHoveredJunctions] = useState<Junction[] | null>(null);
  useEffect(() => {
    if (!map || !hoveredJunctions) return;
    const markers = hoveredJunctions.map((junction) => {
      const element = document.createElement("div");
      element.className = "junction-marker";
      element.setAttribute("aria-hidden", "true");
      return new maplibregl.Marker({ element, anchor: "center" })
        .setLngLat([junction.lon, junction.lat])
        .addTo(map);
    });
    return () => markers.forEach((marker) => marker.remove());
  }, [map, hoveredJunctions]);

  // --- TM05-100: open a saved trail or plan, once ------------------------------------
  const requestHandled = useRef(false);
  const pendingPlan = useRef<number | null>(null);
  useEffect(() => {
    if (!map || !openRequest || requestHandled.current) return;
    requestHandled.current = true;
    pendingPlan.current = openRequest.kind === "plan" ? openRequest.planId : null;
    // Loading is set here, from the request, as a map click sets it from its event.
    setState({ status: "loading", name: openRequest.name });
    setSelected(
      "osmId" in openRequest.trail
        ? { osmId: openRequest.trail.osmId, name: openRequest.name }
        : { wayId: openRequest.trail.wayId, name: openRequest.name },
    );
  }, [map, openRequest]);
  const loadedKey = state?.status === "ready" ? state.detail.source_id : null;
  useEffect(() => {
    const planId = pendingPlan.current;
    if (!loadedKey || planId === null || !session) return;
    pendingPlan.current = null;
    getPlan(session, planId)
      .then((plan) => {
        setPlanDraft({
          trailKey: loadedKey,
          planId: plan.id,
          name: plan.name,
          stopIds: plan.stops.map((stop) => stop.id),
        });
        // A plan's nights can be potential spots, which only the search lists.
        setFinding({ key: loadedKey, finder: { status: "loading" } });
      })
      .catch(() => undefined); // the trail is open; the plan just isn't loaded
  }, [loadedKey, session]);

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
      if (placement.active) return; // the click drops a waypoint (TM05-80)
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
    // TM05-97: a named trail segment that is not under a route opens the trail panel too.
    // The route handler wins where a route is drawn, and the page's handler (Discover)
    // wins where a campsite is: those clicks are left alone here.
    const onWayClick = (event: maplibregl.MapLayerMouseEvent) => {
      if (placement.active) return; // the click drops a waypoint (TM05-80)
      if (isRouteHit(map, event.point)) return;
      if (
        map.getLayer(CAMPSITES_POINT) &&
        map.queryRenderedFeatures(event.point, { layers: [CAMPSITES_POINT] }).length
      ) {
        return;
      }
      const feature = event.features?.[0];
      if (!feature || !isNamedTrail(feature.properties)) return;
      const wayId = sourceIdOf(feature);
      if (!wayId) return;
      const name = String(feature.properties?.name);
      setState({ status: "loading", name });
      setSelected({ wayId, name });
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
    map.on("click", TRAIL_SEGMENTS_HIT, onWayClick);
    map.on("mousemove", ROUTES_HIT, onRouteHover);
    map.on("mousemove", SELECTED_HIT, onSelectedHover);
    map.on("mouseleave", SELECTED_HIT, onSelectedLeave);
    load();

    return () => {
      window.clearTimeout(timer);
      controller?.abort();
      map.off("moveend", onMove);
      map.off("click", ROUTES_HIT, onRouteClick);
      map.off("click", TRAIL_SEGMENTS_HIT, onWayClick);
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
    const request =
      "osmId" in selected
        ? fetchRouteDetail(selected.osmId, withinM, controller.signal)
        : fetchTrailForWay(selected.wayId, withinM, controller.signal);
    request
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
  const framed = useRef<string | null>(null);
  useEffect(() => {
    if (!map || state?.status !== "ready") return;
    const { detail } = state;
    (map.getSource(SELECTED_SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData({
      type: "Feature",
      properties: {},
      geometry: detail.line,
    });
    if (framed.current !== detail.source_id) {
      framed.current = detail.source_id;
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
      // A site past either end has no place on the profile (TM05-73).
      setCursorM(isAlong(site) ? site.distance_along_m : null);
      if (onOpenCampsite) {
        onOpenCampsite({
          id: site.id,
          lon: site.lon,
          lat: site.lat,
          name: site.display_name ?? site.name,
          score: site.score,
          breakdown: site.score_breakdown,
        });
      }
      else map?.flyTo({ center: [site.lon, site.lat], zoom: Math.max(map.getZoom(), 14) });
    },
    [map, onOpenCampsite],
  );

  // TM05-74: picking a search result opens its trail like a map click does; the framing
  // effect above fits the map to it once it loads.
  const pick = (hit: RouteHit) => {
    setState((previous) =>
      previous?.status === "ready" && previous.detail.osm_id === hit.osm_id
        ? previous
        : { status: "loading", name: hit.name },
    );
    setSelected({ osmId: hit.osm_id, name: hit.name });
  };
  const search = <TrailSearch map={map} onPick={pick} />;

  const trailKey = state?.status === "ready" ? state.detail.source_id : null;
  const draft = trailKey ? draftFor(planDraft, trailKey) : null;
  const nightOf: Record<string, number> = {};
  if (draft && worked && worked.trail.source_id === draft.trailKey) {
    for (const stop of worked.stops) if (draft.stopIds.includes(stop.id)) nightOf[stop.id] = stop.night;
  }

  const finder: Finder =
    trailKey && finding?.key === trailKey ? finding.finder : { status: "idle" };
  const finderOpen = finder.status !== "idle";
  const readyDetail = state?.status === "ready" ? state.detail : null;
  const searchPath = readyDetail ? candidatesPath(readyDetail, withinM) : null;
  const candidates = finder.status === "ready" ? (finder.search?.candidates ?? []) : [];
  const nights =
    draft && worked && worked.trail.source_id === draft.trailKey
      ? worked.stops.filter((stop) => draft.stopIds.includes(stop.id))
      : [];

  if (!state) return search;
  return (
    <>
      {search}
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
      planner={
        state.status === "ready" && draft ? (
          <PlanBuilder
            detail={state.detail}
            session={session}
            draft={draft}
            onDraft={setPlanDraft}
            onWorked={setWorked}
          />
        ) : null
      }
      stops={
        session && draft
          ? {
              ids: draft.stopIds,
              nightOf,
              onToggle: (id) => setPlanDraft(toggleStop(draft, id)),
            }
          : undefined
      }
      finder={finder}
      onFind={() => trailKey && setFinding({ key: trailKey, finder: { status: "loading" } })}
      onConnection={(connection) => {
        const target = connectionTarget(connection);
        if (!target) return;
        setHoveredJunctions(null);
        setState({ status: "loading", name: connection.name });
        setSelected(target);
      }}
      onConnectionHover={(connection) => setHoveredJunctions(connection?.junctions ?? null)}
      onCandidate={(candidate) => {
        setCursorM(candidate.distance_along_m);
        setOpenCandidate(candidate);
        map?.easeTo({ center: [candidate.lon, candidate.lat], zoom: Math.max(map.getZoom(), 14) });
      }}
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
      <AlongMarkers
        map={map}
        candidates={candidates}
        nights={nights}
        open={openCandidate && candidates.some((c) => c.id === openCandidate.id) ? openCandidate : null}
        onOpen={setOpenCandidate}
        stop={
          session && draft && openCandidate
            ? {
                chosen: draft.stopIds.includes(openCandidate.id),
                night: nightOf[openCandidate.id],
                onToggle: () => setPlanDraft(toggleStop(draft, openCandidate.id)),
              }
            : undefined
        }
      />
      <FinderEffects
        map={map}
        trailKey={trailKey}
        open={finderOpen}
        path={searchPath}
        campsites={readyDetail?.campsites.items ?? null}
        onResult={(key, next) => setFinding((current) => (current?.key === key ? { key, finder: next } : current))}
      />
    </>
  );
}

/**
 * The search's side effects, kept out of the component above: run the candidate search
 * (again when the corridor changes), and draw the mapped campsites along the trail while
 * the finder is open.
 */
function FinderEffects({
  map,
  trailKey,
  open,
  path,
  campsites,
  onResult,
}: {
  map: maplibregl.Map | null;
  trailKey: string | null;
  open: boolean;
  path: string | null;
  campsites: CampsiteAlong[] | null;
  onResult: (key: string, finder: Finder) => void;
}) {
  const report = useRef(onResult);
  useEffect(() => {
    report.current = onResult;
  }, [onResult]);

  useEffect(() => {
    if (!open || !trailKey || !path) return;
    const controller = new AbortController();
    report.current(trailKey, { status: "loading" });
    fetchCandidates(path, controller.signal)
      .then((search) => report.current(trailKey, { status: "ready", search }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        report.current(trailKey, {
          status: "error",
          message: `Potential spots are unavailable right now (${error instanceof Error ? error.message : String(error)}). Mapped campsites are listed below.`,
        });
      });
    return () => controller.abort();
  }, [open, trailKey, path]);

  useEffect(() => {
    const source = map?.getSource(ALONG_SOURCE) as maplibregl.GeoJSONSource | undefined;
    if (!source) return;
    if (!open || !campsites) {
      source.setData(EMPTY);
      return;
    }
    const points: Feature<Point>[] = campsites.map((site) => ({
      type: "Feature",
      properties: { id: site.id },
      geometry: { type: "Point", coordinates: [site.lon, site.lat] },
    }));
    source.setData({ type: "FeatureCollection", features: points });
  }, [map, open, campsites]);

  return null;
}
