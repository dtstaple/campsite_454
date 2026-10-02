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
import "./trails.css";

/** Below this zoom a route list would be most of a region; skip the request. */
const MIN_ROUTE_ZOOM = 9;
const DEBOUNCE_MS = 400;
const DEFAULT_WITHIN_M = 500;

interface Props {
  map: maplibregl.Map | null;
}

export default function TrailInsight({ map }: Props) {
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
    setSelected(null);
    setState(null);
    setCursorM(null);
    framed.current = null;
    (map?.getSource(SELECTED_SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData(EMPTY);
    (map?.getSource(ALONG_SOURCE) as maplibregl.GeoJSONSource | undefined)?.setData(EMPTY);
  }, [map]);

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
      map?.flyTo({ center: [site.lon, site.lat], zoom: Math.max(map.getZoom(), 14) });
    },
    [map],
  );

  if (!state) return null;
  return (
    <TrailPanel
      state={state}
      cursorM={cursorM}
      withinM={withinM}
      onCursor={setCursorM}
      onWithin={setWithinM}
      onCampsite={showCampsite}
      onClose={close}
    />
  );
}
