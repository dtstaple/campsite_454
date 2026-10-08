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
import { createPortal } from "react-dom";
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
import {
  addMapLayers,
  addMapSources,
  addTerrainLayers,
  CLICKABLE,
  CLICKABLE_IDS,
  EMPTY,
  LAYERS,
  setHillshadeVisible,
} from "../map/layers";
import { popupContent } from "../map/popups";
import { sourceIdOf, withSourceIds } from "../map/featureIds";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useSession } from "../session";
import ModeSwitcher from "../modes/ModeSwitcher";
import LayerPanel from "../components/LayerPanel";
import { requestFromState, type OpenRequest } from "../profile/openRequest";
import SaveButton from "../components/SaveButton";
import CampsiteDetail from "../campsite/CampsiteDetail";
import TrailInsight from "../trails/TrailInsight";
import Waypoints from "../waypoints/Waypoints";
import { placement } from "../waypoints/placement";
import BasemapToggle from "../basemap/BasemapToggle";
import SatelliteLayers from "../basemap/SatelliteLayers";
import { useBasemap } from "../basemap/useBasemap";
import { isRouteHit } from "../trails/mapLayers";
import { isNamedTrail } from "../trails/format";
import { selectionFromFeature, type CampsiteSelection } from "../campsite/selection";
import { useCampsiteHover } from "../campsite/useCampsiteHover";
import { DEFAULT_MODE_ID, modeById, type ModeId } from "../modes/modes";
import {
  loadSaved,
  save as saveCampsite,
  SaveError,
  unsave as unsaveCampsite,
  type SavedCampsite,
} from "../saved";
import type { FeatureCollection as GeoJsonFeatureCollection } from "geojson";
import { addContourLayers, setContourBasemap, setContoursVisible } from "../map/contours";
import StartLocation from "../location/StartLocation";
import {
  addSlopeLayer,
  defaultSlopeOpacity,
  setSlopeOpacity as applySlopeOpacity,
  setSlopeVisible,
} from "../slope/slopeLayer";
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
  // The map, once its base layers exist, for features that add their own (TrailInsight).
  const [mapInstance, setMapInstance] = useState<maplibregl.Map | null>(null);
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

  // Hillshade is a raster the map fetches itself, so it is shown and hidden in place
  // rather than going through refresh(). The ref lets the once-only load handler read it.
  const [terrain, setTerrain] = useState(() => modeById(DEFAULT_MODE_ID).terrain);
  // Standard or satellite basemap, remembered across reloads (TM05-65).
  const [basemap, setBasemap] = useBasemap();
  const terrainRef = useRef(terrain);
  useEffect(() => {
    terrainRef.current = terrain;
    if (map.current && styleReady.current) {
      // No hillshade over satellite imagery (TM05-65); SatelliteLayers restores it.
      setHillshadeVisible(map.current, terrain && basemap !== "satellite");
    }
  }, [terrain, basemap]);

  // Contour lines (TM05-83): like the hillshade, drawn by the map itself and shown or
  // hidden in place; retinted for satellite imagery.
  const [contours, setContours] = useState(true);
  const contoursRef = useRef(contours);
  const basemapRef = useRef(basemap);
  useEffect(() => {
    contoursRef.current = contours;
    basemapRef.current = basemap;
    if (map.current && styleReady.current) {
      setContoursVisible(map.current, contours);
      setContourBasemap(map.current, basemap);
    }
  }, [contours, basemap]);

  // Slope-angle shading (TM05-84): off until asked for, with its own opacity.
  const [slope, setSlope] = useState(false);
  const [slopeOpacity, setSlopeOpacity] = useState(defaultSlopeOpacity);
  const slopeRef = useRef({ on: slope, opacity: slopeOpacity });
  useEffect(() => {
    slopeRef.current = { on: slope, opacity: slopeOpacity };
    if (map.current && styleReady.current) {
      setSlopeVisible(map.current, slope);
      applySlopeOpacity(map.current, slopeOpacity);
    }
  }, [slope, slopeOpacity]);

  const switchMode = useCallback((id: ModeId) => {
    const next = modeById(id);
    setModeId(id);
    setEnabled({ ...next.layers });
    setTerrain(next.terrain);
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
  // The selected campsite (TM05-66, TM05-69): its detail panel is open and it is raised
  // on the map. Set from a map click or the trail panel's list; one at a time.
  const [selection, setSelection] = useState<CampsiteSelection | null>(null);
  // The campsite row hovered in the trail panel's list, lit up on the map (TM05-69).
  const [hoveredCampsite, setHoveredCampsite] = useState<string | null>(null);
  useCampsiteHover(mapInstance, hoveredCampsite);

  // The campsite whose popup is open, and the slot in that popup the save button is
  // portalled into. The map's click handler only records this; the button itself is
  // rendered below from current state, so it needs no refs to stay in step.
  const [popupSave, setPopupSave] = useState<{
    campsite: SavedCampsite;
    slot: HTMLElement;
  } | null>(null);

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
          source?.setData(withSourceIds(collection as unknown as GeoJsonFeatureCollection));
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

  /** Save or unsave, from the popup or the Saved panel. */
  const toggleSaved = useCallback(
    async (campsite: SavedCampsite) => {
      if (!session) {
        setSignInPrompt(true);
        return;
      }

      setSaveError(null);
      const alreadySaved = saved.some((entry) => entry.id === campsite.id);
      try {
        const next = alreadySaved
          ? await unsaveCampsite(campsite.id, session, saved)
          : await saveCampsite(campsite, session, saved);
        setSaved(next);
      } catch (caught) {
        setSaveError(caught instanceof SaveError ? caught.message : String(caught));
      }
    },
    [session, saved],
  );

  // TM05-100: an item clicked on the Profile page arrives as router state. It is taken
  // once, and the history entry is replaced so a reload does not open it again.
  const location = useLocation();
  const navigate = useNavigate();
  const [openRequest] = useState<OpenRequest | null>(() => requestFromState(location.state));
  useEffect(() => {
    if (openRequest) navigate(location.pathname, { replace: true, state: null });
    // Only on arrival.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const openedCampsite = useRef(false);
  useEffect(() => {
    if (!mapInstance || openRequest?.kind !== "campsite" || openedCampsite.current) return;
    openedCampsite.current = true;
    mapInstance.jumpTo({
      center: [openRequest.lon, openRequest.lat],
      zoom: Math.max(mapInstance.getZoom(), 13),
    });
    // The campsite panel opens with the raised pin (TM05-69), whether or not the
    // Campsites layer is on.
    setSelection({
      id: openRequest.id,
      lon: openRequest.lon,
      lat: openRequest.lat,
      name: openRequest.name,
      score: null,
    });
  }, [mapInstance, openRequest]);

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
    // Zoom and compass, bottom right where a thumb or a mouse already rests. The compass
    // also shows pitch, and clicking it resets north.
    instance.addControl(
      new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }),
      "bottom-right",
    );

    instance.on("load", () => {
      // First, so it lands under the basemap labels and under every data layer.
      addTerrainLayers(instance, terrainRef.current);
      addContourLayers(instance, contoursRef.current, basemapRef.current);
      addSlopeLayer(instance, slopeRef.current.on, slopeRef.current.opacity);
      addMapSources(instance);
      addMapLayers(instance);

      styleReady.current = true;
      setMapInstance(instance);
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
      // This click drops a new waypoint (TM05-80); nothing else should open for it.
      if (placement.active) return;
      // A named route opens the trail panel (TrailInsight); no segment popup on top of it.
      if (isRouteHit(instance, event.point)) return;
      const hit = topClickable(event.point);
      // Empty map clears the selected campsite (TM05-69).
      if (!hit) {
        setSelection(null);
        return;
      }
      const { layer, feature } = hit;

      // A named trail segment opens the trail panel (TrailInsight, TM05-97); only an
      // unnamed segment keeps the small popup.
      if (layer === "trails" && isNamedTrail(feature.properties)) return;

      // A campsite opens its detail panel (TM05-66) instead of a popup.
      if (layer === "campsites" && sourceIdOf(feature)) {
        setSelection(selectionFromFeature(feature, sourceIdOf(feature)));
        return;
      }

      // setDOMContent rather than setHTML, so the campsite actions slot is a node we
      // already hold rather than one to re-find once the popup exists.
      const { element, actions } = popupContent(layer, feature.properties);
      const popup = new maplibregl.Popup({ closeButton: true })
        .setLngLat(event.lngLat)
        .setDOMContent(element)
        .addTo(instance);

      const campsite: SavedCampsite = {
        // The Feature id is the campsite's source_id, which is what the save endpoint
        // accepts -- see docs/api.md. Sent back unchanged, never parsed.
        id: sourceIdOf(feature),
        name: String(feature.properties?.name || "") || "Unnamed campsite",
        lon: event.lngLat.lng,
        lat: event.lngLat.lat,
      };

      // Only offer saving when the feature carries an id to send back. Closing clears
      // the portal -- unless another popup has already replaced it.
      if (actions && campsite.id) {
        setPopupSave({ campsite, slot: actions });
        popup.on("close", () =>
          setPopupSave((current) => (current?.slot === actions ? null : current)),
        );
      }
    });
    instance.on("mousemove", (event: maplibregl.MapMouseEvent) => {
      instance.getCanvas().style.cursor = topClickable(event.point) ? "pointer" : "";
    });

    return () => {
      window.clearTimeout(debounce.current);
      inFlight.current?.abort();
      styleReady.current = false;
      setMapInstance(null);
      instance.remove();
      map.current = null;
    };
  }, [refresh]);

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
          terrain={terrain}
          onTerrain={setTerrain}
          contours={contours}
          onContours={setContours}
          slope={slope}
          onSlope={setSlope}
          slopeOpacity={slopeOpacity}
          onSlopeOpacity={setSlopeOpacity}
          onRegion={flyToRegion}
        />
        {/* Keyed by session: signing in or out starts the waypoints afresh. */}
        <Waypoints
          key={session?.token ?? "signed-out"}
          map={mapInstance}
          session={session}
          focus={openRequest?.kind === "waypoint" ? openRequest : null}
        />
      </div>


      {popupSave &&
        createPortal(
          <SaveButton
            key={popupSave.campsite.id}
            isSaved={saved.some((entry) => entry.id === popupSave.campsite.id)}
            onToggle={() => toggleSaved(popupSave.campsite)}
          />,
          popupSave.slot,
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
        <div className="map-notice" role="status">
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

      <TrailInsight
        map={mapInstance}
        openRequest={
          openRequest?.kind === "trail" || openRequest?.kind === "plan" ? openRequest : null
        }
        onOpenCampsite={setSelection}
        onHoverCampsite={setHoveredCampsite}
      />
      <CampsiteDetail
        map={mapInstance}
        selection={selection}
        onClose={() => setSelection(null)}
        renderSave={(detail) => {
          const campsite = {
            id: detail.id,
            name: detail.display_name ?? "Campsite",
            lon: detail.lon,
            lat: detail.lat,
          };
          return (
            <SaveButton
              key={detail.id}
              isSaved={saved.some((entry) => entry.id === detail.id)}
              onToggle={() => toggleSaved(campsite)}
            />
          );
        }}
      />
      <StartLocation map={mapInstance} onRegion={flyToRegion} />
      <SatelliteLayers map={mapInstance} basemap={basemap} terrain={terrain} />
      <BasemapToggle value={basemap} onChange={setBasemap} />
    </div>
  );
}
