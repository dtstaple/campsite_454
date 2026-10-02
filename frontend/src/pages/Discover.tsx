/**
 * Discover: the map.
 *
 * Moved here from App.tsx when the app gained routes; the map itself is unchanged.
 * Everything here follows docs/api.md.
 *
 * The session is no longer owned by this component -- it comes from SessionProvider, so
 * the header can sign out from any route and this page still sees it.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
// No stylesheet imports here. maplibre-gl.css is imported in main.tsx and App.css in
// App.tsx: the vendor sheet has to load before ours or `.maplibregl-map` overrides `.map`
// and the container collapses, so the order is decided in one place only.
import {
  bboxCenter,
  DEFAULT_REGION,
  DEFAULT_ZOOM,
  regionAt,
  regionCamera,
  type Region,
} from "../regions";
import { addMapLayers, addMapSources, CLICKABLE, CLICKABLE_IDS, EMPTY, LAYERS } from "../map/layers";
import { popupFor } from "../map/popups";
import { Link } from "react-router-dom";
import { useSession } from "../session";
import ModeSwitcher from "../modes/ModeSwitcher";
import LayerPanel from "../components/LayerPanel";
import SavedPanel from "../components/SavedPanel";
import { DEFAULT_MODE_ID, modeById, type ModeId } from "../modes/modes";
import {
  loadSaved,
  save as saveCampsite,
  SaveError,
  unsave as unsaveCampsite,
  type SavedCampsite,
} from "../saved";
import type { FeatureCollection as GeoJsonFeatureCollection } from "geojson";
import {
  ApiError,
  fetchMapData,
  layerVisibleAtZoom,
  simplifyForZoom,
  type Bbox,
  type LayerName,
  type Metadata,
} from "../api";

/*
 * Basemap. Stadia's "Alidade Smooth Dark" serves keyless from allowlisted domains
 * including localhost, verified against the live endpoint. Read from env so a key
 * can be appended for a deployed domain without touching code.
 */
const MAP_STYLE_URL =
  import.meta.env.VITE_MAP_STYLE_URL ??
  "https://tiles.stadiamaps.com/styles/alidade_smooth_dark.json";

// Opens on the region with the most data -- see DEFAULT_REGION in regions.ts.
const INITIAL_CENTER = bboxCenter(DEFAULT_REGION.bbox);
const DEBOUNCE_MS = 400;

export default function Discover() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const styleReady = useRef(false);
  const inFlight = useRef<AbortController | null>(null);
  const debounce = useRef<number | undefined>(undefined);

  // The activity mode decides which layers start on. Switching mode resets the toggles
  // to that mode's defaults; toggling a layer afterwards is the user's call until the
  // next switch.
  const [modeId, setModeId] = useState<ModeId>(DEFAULT_MODE_ID);
  const mode = modeById(modeId);
  const [enabled, setEnabled] = useState<Record<LayerName, boolean>>(() => ({
    ...modeById(DEFAULT_MODE_ID).layers,
  }));

  const switchMode = useCallback((id: ModeId) => {
    setModeId(id);
    setEnabled({ ...modeById(id).layers });
  }, []);

  const toggleLayer = useCallback((layer: LayerName, on: boolean) => {
    setEnabled((previous) => ({ ...previous, [layer]: on }));
  }, []);
  // refresh() reads the toggles through a ref so it can stay a stable callback.
  // Synced in an effect rather than during render, and declared before the effect
  // that calls refresh() so the ref is already current when that one runs.
  const enabledRef = useRef(enabled);
  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<Partial<Record<LayerName, Metadata>>>({});

  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  // Tracked only to say which region shortcut is current; the map owns the real camera.
  const [center, setCenter] = useState<[number, number]>(INITIAL_CENTER);
  const [fromCache, setFromCache] = useState(false);

  // From the provider above the router, so signing out in the header reaches the Saved
  // panel below.
  const { session } = useSession();
  // Starts empty and is filled by the effect below, because the list now comes from the
  // server rather than from this browser's storage.
  const [saved, setSaved] = useState<SavedCampsite[]>([]);

  // The popup's save button is a plain DOM node created inside the map-setup effect,
  // which runs once. Reading session and saved through refs keeps that handler from
  // closing over the values they had on the first render -- the same reason `enabled`
  // is read through a ref above.
  const sessionRef = useRef(session);
  const savedRef = useRef(saved);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);
  useEffect(() => {
    savedRef.current = saved;
  }, [saved]);

  // Set by the popup's save button when nobody is signed in, so the sign-in prompt is
  // an answer to an action rather than a nag. Declared before the effect that clears it:
  // a closure reading it later happens to work, but reading a const above its own
  // declaration is the kind of thing that stops working when someone moves a line.
  const [signInPrompt, setSignInPrompt] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Signing in or out swaps whose list this is. loadSaved returns [] when signed out,
  // so the panel empties rather than showing the previous user's saves.
  //
  // `cancelled` guards against a fast sign-out landing before the previous user's
  // in-flight response, which would otherwise repopulate the panel after it emptied.
  useEffect(() => {
    let cancelled = false;
    void loadSaved(session).then((list) => {
      if (!cancelled) setSaved(list);
    });
    if (session) setSignInPrompt(false);
    return () => {
      cancelled = true;
    };
  }, [session]);

  /** Fetch the viewport in one request and push each layer into its source. */
  const refresh = useCallback(async () => {
    const current = map.current;
    if (!current || !styleReady.current) return;

    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    const bbox = current.getBounds().toArray().flat() as Bbox;
    const currentZoom = current.getZoom();
    const simplify = simplifyForZoom(currentZoom);

    // A layer is drawn only when it is both toggled on and meaningful at this zoom.
    const shown = (layer: LayerName) =>
      enabledRef.current[layer] && layerVisibleAtZoom(layer, currentZoom);

    const wanted = LAYERS.map((l) => l.name).filter(shown);

    // Nothing to draw at all: clear the sources and skip the request entirely.
    if (wanted.length === 0) {
      for (const layer of LAYERS) {
        (current.getSource(layer.name) as maplibregl.GeoJSONSource | undefined)?.setData(EMPTY);
        setMeta((previous) => ({ ...previous, [layer.name]: undefined }));
      }
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const { data, cached } = await fetchMapData(
        bbox,
        simplify,
        wanted,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setFromCache(cached);

      for (const layer of LAYERS) {
        const source = current.getSource(layer.name) as maplibregl.GeoJSONSource | undefined;
        const collection = data.layers[layer.name];
        if (shown(layer.name) && collection) {
          source?.setData(collection as unknown as GeoJsonFeatureCollection);
          setMeta((previous) => ({ ...previous, [layer.name]: collection.metadata }));
        } else {
          source?.setData(EMPTY);
          setMeta((previous) => ({ ...previous, [layer.name]: undefined }));
        }
      }
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  /** Save or unsave from the popup. Stable, so the map effect never re-runs for it. */
  const toggleSaved = useCallback(async (campsite: SavedCampsite) => {
    const current = sessionRef.current;
    if (!current) {
      setSignInPrompt(true);
      return;
    }

    setSaveError(null);
    const list = savedRef.current;
    const alreadySaved = list.some((entry) => entry.id === campsite.id);
    try {
      const next = alreadySaved
        ? await unsaveCampsite(campsite.id, current, list)
        : await saveCampsite(campsite, current, list);
      setSaved(next);
    } catch (caught) {
      setSaveError(caught instanceof SaveError ? caught.message : String(caught));
    }
    // The setters are stable by contract, but listing them lets React Compiler verify
    // that rather than skip optimising the component.
  }, [setSaved, setSaveError, setSignInPrompt]);

  /** Centre the map on a saved campsite. */
  const flyToSaved = useCallback((campsite: SavedCampsite) => {
    map.current?.flyTo({ center: [campsite.lon, campsite.lat], zoom: Math.max(13, DEFAULT_ZOOM) });
  }, []);

  /** Jump to one of the regions that has data. */
  const flyToRegion = useCallback((region: Region) => {
    const current = map.current;
    if (current) current.flyTo(regionCamera(current, region));
  }, []);

  const currentRegion = regionAt(center);

  // --- map setup, once ------------------------------------------------------------

  useEffect(() => {
    if (!mapContainer.current) return;

    const instance = new maplibregl.Map({
      container: mapContainer.current,
      style: MAP_STYLE_URL,
      center: INITIAL_CENTER,
      zoom: DEFAULT_ZOOM,
    });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl(), "top-right");

    instance.on("load", () => {
      addMapSources(instance);
      addMapLayers(instance);

      styleReady.current = true;
      void refresh();
    });

    // Refetch when the viewport settles, debounced so a drag is one request.
    const onIdle = () => {
      setZoom(instance.getZoom());
      const { lng, lat } = instance.getCenter();
      setCenter([lng, lat]);
      window.clearTimeout(debounce.current);
      debounce.current = window.setTimeout(() => void refresh(), DEBOUNCE_MS);
    };
    instance.on("moveend", onIdle);
    instance.on("zoomend", onIdle);

    /*
     * Popups for every clickable layer. One map-wide handler rather than one per layer,
     * because a click often lands on several at once -- a campsite beside a stream on a
     * trail -- and per-layer handlers would open a popup for each. CLICKABLE's order
     * decides which one wins. Querying the `-hit` layers is what makes a hairline trail
     * clickable without pixel-perfect aim.
     */
    const topClickable = (point: maplibregl.PointLike) => {
      if (!styleReady.current) return undefined;
      const hits = instance.queryRenderedFeatures(point, { layers: CLICKABLE_IDS });
      for (const entry of CLICKABLE) {
        const feature = hits.find((hit) => hit.layer.id === entry.id);
        if (feature) return { layer: entry.layer, feature };
      }
      return undefined;
    };

    instance.on("click", (event: maplibregl.MapMouseEvent) => {
      const hit = topClickable(event.point);
      if (!hit) return;
      const { layer, feature } = hit;

      // setDOMContent rather than setHTML: the campsite save button needs a real
      // listener, and a string popup would mean re-finding the node and guessing when
      // it exists.
      const content = document.createElement("div");
      content.innerHTML = popupFor(layer, feature.properties);

      if (layer === "campsites") {
        const campsite: SavedCampsite = {
          // The Feature id is the campsite's source_id, which is what the save endpoint
          // accepts -- see docs/api.md. Sent back unchanged, never parsed.
          id: String(feature.id ?? ""),
          name: String(feature.properties?.name || "") || "Unnamed campsite",
          lon: event.lngLat.lng,
          lat: event.lngLat.lat,
        };

        const button = document.createElement("button");
        button.type = "button";
        button.className = "popup-save";

        const paint = () => {
          const isSaved = savedRef.current.some((entry) => entry.id === campsite.id);
          button.textContent = isSaved ? "Saved ✓" : "Save";
          button.classList.toggle("is-saved", isSaved);
          button.setAttribute("aria-pressed", String(isSaved));
        };
        paint();

        button.addEventListener("click", async () => {
          button.disabled = true;
          await toggleSaved(campsite);
          button.disabled = false;
          paint();
        });

        // Only offer it when the feature carries an id to send back.
        if (campsite.id) content.querySelector(".popup")?.appendChild(button);
      }

      new maplibregl.Popup({ closeButton: true })
        .setLngLat(event.lngLat)
        .setDOMContent(content)
        .addTo(instance);
    });
    instance.on("mousemove", (event: maplibregl.MapMouseEvent) => {
      instance.getCanvas().style.cursor = topClickable(event.point) ? "pointer" : "";
    });

    return () => {
      window.clearTimeout(debounce.current);
      inFlight.current?.abort();
      styleReady.current = false;
      instance.remove();
      map.current = null;
    };
  }, [refresh, toggleSaved]);

  // Toggling a layer refetches rather than hiding, so a layer turned back on is current.
  useEffect(() => {
    void refresh();
  }, [enabled, refresh]);

  const truncated = LAYERS.filter((layer) => meta[layer.name]?.truncated);

  return (
    <div className="app">
      <div ref={mapContainer} className="map" />

      <div className="overlay-left">
        <ModeSwitcher active={mode.id} onChange={switchMode} />
        <LayerPanel
          mode={mode}
          enabled={enabled}
          meta={meta}
          zoom={zoom}
          loading={loading}
          fromCache={fromCache}
          currentRegionId={currentRegion?.id}
          onToggle={toggleLayer}
          onRegion={flyToRegion}
        />
      </div>

      {session && (
        <SavedPanel
          saved={saved}
          onShow={flyToSaved}
          onUnsave={(campsite) => void toggleSaved(campsite)}
        />
      )}

      {signInPrompt && !session && (
        <div className="banner warn">
          <Link to="/login">Sign in</Link> to save campsites.{" "}
          <button type="button" className="link-button" onClick={() => setSignInPrompt(false)}>
            Dismiss
          </button>
        </div>
      )}

      {saveError && <div className="banner error">{saveError}</div>}

      {error && <div className="banner error">{error}</div>}

      {truncated.length > 0 && !error && (
        <div className="banner warn">
          Zoom in to see all features — showing{" "}
          {truncated.map((layer, index) => {
            const info = meta[layer.name]!;
            return (
              <span key={layer.name}>
                {index > 0 ? ", " : ""}
                <b>{info.returned.toLocaleString()}</b> of{" "}
                <b>{info.matched.toLocaleString()}</b> {layer.label.toLowerCase()}
              </span>
            );
          })}
          .
        </div>
      )}
    </div>
  );
}
