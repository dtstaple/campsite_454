/**
 * Campsite detail (TM05-66): owns the selected campsite's data and its place on the map.
 *
 * The page passes the selection (from a map click or the trail panel's list), the map,
 * and a Save button builder so saving shares the page's session and saved list. This
 * component fetches /api/campsites/<id>/detail/ for the panel; SelectedCampsite (TM05-69)
 * raises a pin over the site and brings it into view beside the panel.
 */

import { useEffect, useState, type ReactNode } from "react";
import type * as maplibregl from "maplibre-gl";
import {
  CampsiteApiError,
  fetchCampsiteDetail,
  fetchViewshed,
  type CampsiteDetail as Detail,
} from "./api";
import { showViewshed } from "../terrain/zonesLayer";
import CampsitePanel, { type CampsiteScore, type CampsiteState } from "./CampsitePanel";
import SelectedCampsite from "./SelectedCampsite";
import type { CampsiteSelection } from "./selection";
import "./campsite.css";

interface Props {
  map: maplibregl.Map | null;
  /** The selected campsite (TM05-69): set from a map click or the trail panel's list. */
  selection: CampsiteSelection | null;
  onClose: () => void;
  renderSave: (detail: Detail) => ReactNode;
}

/**
 * The detail response's score once it has arrived: it is fetched fresh with the user's
 * weights (TM05-115), where the selection's may come from a map feature drawn earlier.
 */
function panelScore(state: CampsiteState, selection: CampsiteSelection | null): CampsiteScore {
  if (state.status === "ready" && state.detail.score_breakdown != null) {
    return { breakdown: state.detail.score_breakdown, total: state.detail.score ?? null };
  }
  return { breakdown: selection?.breakdown ?? null, total: selection?.score ?? null };
}

export default function CampsiteDetail({ map, selection, onClose, renderSave }: Props) {
  const campsiteId = selection?.id ?? null;
  const [state, setState] = useState<CampsiteState>({ status: "loading" });
  const [loadedId, setLoadedId] = useState<string | null>(null);
  // "Show what I can see" (TM05-142): the site whose viewshed is drawn, if any.
  const [viewOf, setViewOf] = useState<string | null>(null);

  useEffect(() => {
    if (!map) return;
    if (!viewOf || viewOf !== campsiteId) {
      showViewshed(map, null);
      return;
    }
    const controller = new AbortController();
    fetchViewshed(viewOf, controller.signal)
      .then((feature) => showViewshed(map, feature))
      .catch(() => {
        if (!controller.signal.aborted) setViewOf(null);
      });
    return () => controller.abort();
  }, [map, viewOf, campsiteId]);

  // The viewshed belongs to the open site: closing the panel clears it.
  useEffect(() => () => setViewOf(null), [campsiteId]);

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

  useEffect(() => {
    if (!campsiteId) return;
    // Capture phase, and stop it there: Escape clears the campsite first and leaves the
    // trail panel (which also listens for Escape) open. A second Escape closes the trail.
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopImmediatePropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, [campsiteId, onClose]);

  if (!campsiteId) return null;
  // Until the newly selected site's data arrives, show loading rather than the previous one.
  const shown: CampsiteState = loadedId === campsiteId ? state : { status: "loading" };
  return (
    <>
      <CampsitePanel
        state={shown}
        score={panelScore(shown, selection)}
        saveButton={shown.status === "ready" ? renderSave(shown.detail) : null}
        onClose={onClose}
        viewshed={{
          showing: viewOf === campsiteId,
          onToggle: () => setViewOf((current) => (current === campsiteId ? null : campsiteId)),
        }}
      />
      <SelectedCampsite
        map={map}
        selection={selection}
        displayName={shown.status === "ready" ? shown.detail.display_name : null}
      />
    </>
  );
}
