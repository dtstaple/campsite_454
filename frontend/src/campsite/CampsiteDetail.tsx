/**
 * Campsite detail (TM05-66): owns the selected campsite's data and its place on the map.
 *
 * The page passes the selected id (from a map click or the trail panel's list), the map,
 * and a Save button builder so saving shares the page's session and saved list. This
 * component fetches /api/campsites/<id>/detail/, flies to the site leaving room for the
 * panel, and marks it on the map.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import * as maplibregl from "maplibre-gl";
import { CampsiteApiError, fetchCampsiteDetail, type CampsiteDetail as Detail } from "./api";
import CampsitePanel, { type CampsiteState } from "./CampsitePanel";
import "./campsite.css";

interface Props {
  map: maplibregl.Map | null;
  campsiteId: string | null;
  onClose: () => void;
  renderSave: (detail: Detail) => ReactNode;
}

export default function CampsiteDetail({ map, campsiteId, onClose, renderSave }: Props) {
  const [state, setState] = useState<CampsiteState>({ status: "loading" });
  const [loadedId, setLoadedId] = useState<string | null>(null);

  useEffect(() => {
    if (!campsiteId) return;
    const controller = new AbortController();
    fetchCampsiteDetail(campsiteId, controller.signal)
      .then((detail) => {
        setState({ status: "ready", detail });
        setLoadedId(campsiteId);
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          message: error instanceof CampsiteApiError ? error.message : String(error),
        });
        setLoadedId(campsiteId);
      });
    return () => controller.abort();
  }, [campsiteId]);

  // Fly to the site and pin it once its data is in.
  const marker = useRef<maplibregl.Marker | null>(null);
  useEffect(() => {
    if (!map || state.status !== "ready" || !campsiteId) return;
    const { lon, lat } = state.detail;
    map.flyTo({
      center: [lon, lat],
      zoom: Math.max(map.getZoom(), 15),
      padding: { top: 40, bottom: 40, left: 260, right: 400 },
    });
    if (!marker.current) {
      const element = document.createElement("div");
      element.className = "campsite-selected-marker";
      marker.current = new maplibregl.Marker({ element });
    }
    marker.current.setLngLat([lon, lat]).addTo(map);
  }, [map, state, campsiteId]);

  useEffect(() => {
    if (campsiteId) return;
    marker.current?.remove();
    marker.current = null;
  }, [campsiteId]);

  useEffect(() => {
    if (!campsiteId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [campsiteId, onClose]);

  if (!campsiteId) return null;
  // Until the newly selected site's data arrives, show loading rather than the previous one.
  const shown: CampsiteState = loadedId === campsiteId ? state : { status: "loading" };
  return (
    <CampsitePanel
      state={shown}
      saveButton={shown.status === "ready" ? renderSave(shown.detail) : null}
      onClose={onClose}
    />
  );
}
