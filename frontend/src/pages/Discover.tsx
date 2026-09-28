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
// maplibre-gl.css is imported in main.tsx, not here: it has to load before
// App.css or `.maplibregl-map` overrides `.map` and the container collapses.
import "../App.css";
import { mapColors, mapPaint } from "../theme";
import {
  bboxCenter,
  DEFAULT_REGION,
  DEFAULT_ZOOM,
  REGIONS,
  regionAt,
  regionCamera,
  type Region,
} from "../regions";
import { Link } from "react-router-dom";
import { storedSession } from "../auth";
import { useSession } from "../session";
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
  MIN_ZOOM_FOR_LINEWORK,
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

const LAYERS: { name: LayerName; label: string }[] = [
  { name: "public-land", label: "Public land" },
  { name: "water", label: "Water" },
  { name: "trails", label: "Trails" },
  { name: "campsites", label: "Campsites" },
];

const EMPTY: GeoJsonFeatureCollection = { type: "FeatureCollection", features: [] };

export default function Discover() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const styleReady = useRef(false);
  const inFlight = useRef<AbortController | null>(null);
  const debounce = useRef<number | undefined>(undefined);

  const [enabled, setEnabled] = useState<Record<LayerName, boolean>>({
    "public-land": true,
    water: true,
    trails: true,
    campsites: true,
  });
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
  // panel below. storedSession() is still read directly for the initial `saved` value,
  // to fill the list on the first paint rather than a tick later.
  const { session } = useSession();
  const [saved, setSaved] = useState<SavedCampsite[]>(() => loadSaved(storedSession()));

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
  useEffect(() => {
    setSaved(loadSaved(session));
    if (session) setSignInPrompt(false);
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
      // Colours come from theme.css so there is one place to retheme.
      const colour = mapColors();
      const paint = mapPaint();

      // One native GeoJSON source per layer; the API output goes in unmodified.
      for (const layer of LAYERS) {
        instance.addSource(layer.name, { type: "geojson", data: EMPTY });
      }

      // Public land first, so every other layer draws on top of it. It is background:
      // a quiet tint saying which ground is legally campable, under the water, trails
      // and campsites the user actually came to read.
      instance.addLayer({
        id: "public-land-fill",
        type: "fill",
        source: "public-land",
        paint: {
          "fill-color": colour.publicLand,
          "fill-opacity": paint.publicLandFillOpacity,
        },
      });
      instance.addLayer({
        id: "public-land-outline",
        type: "line",
        source: "public-land",
        paint: {
          "line-color": colour.publicLand,
          "line-width": paint.publicLandLineWidth,
          "line-opacity": paint.publicLandLineOpacity,
        },
      });

      // Water: polygons filled, lines stroked. docs/api.md says one collection
      // carries both, so each is filtered by geometry type rather than endpoint.
      instance.addLayer({
        id: "water-fill",
        type: "fill",
        source: "water",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": colour.water, "fill-opacity": paint.waterFillOpacity },
      });
      instance.addLayer({
        id: "water-line",
        type: "line",
        source: "water",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: {
          "line-color": colour.water,
          "line-width": paint.waterLineWidth,
          "line-opacity": paint.waterLineOpacity,
        },
      });

      instance.addLayer({
        id: "trails-line",
        type: "line",
        source: "trails",
        paint: {
          "line-color": colour.trails,
          "line-width": paint.trailsWidth,
          "line-opacity": paint.trailsOpacity,
        },
      });

      instance.addLayer({
        id: "campsites-point",
        type: "circle",
        source: "campsites",
        paint: {
          "circle-radius": paint.campsitesRadius,
          "circle-color": colour.campsites,
          "circle-opacity": paint.campsitesOpacity,
          "circle-stroke-width": paint.campsitesStrokeWidth,
          "circle-stroke-color": colour.campsiteStroke,
        },
      });

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

    // Campsite popups.
    instance.on("click", "campsites-point", (event: maplibregl.MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;

      const campsite: SavedCampsite = {
        // The Feature id is the campsite's source_id, which is what the save endpoint
        // accepts -- see docs/api.md. Sent back unchanged, never parsed.
        id: String(feature.id ?? ""),
        name: String(feature.properties?.name || "") || "Unnamed campsite",
        lon: event.lngLat.lng,
        lat: event.lngLat.lat,
      };

      // setDOMContent rather than setHTML: the save button needs a real listener, and
      // a string popup would mean re-finding the node and guessing when it exists.
      const content = document.createElement("div");
      content.innerHTML = campsitePopup(feature.properties);

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

      new maplibregl.Popup({ closeButton: true })
        .setLngLat(event.lngLat)
        .setDOMContent(content)
        .addTo(instance);
    });
    instance.on("mouseenter", "campsites-point", () => {
      instance.getCanvas().style.cursor = "pointer";
    });
    instance.on("mouseleave", "campsites-point", () => {
      instance.getCanvas().style.cursor = "";
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

      <div className="panel">
        {/* Data sits in a few regions hundreds of miles apart, so free panning mostly
            finds empty map. These jump straight to the places that have something. */}
        <div className="panel-title">Regions</div>
        <div className="regions" role="group" aria-label="Jump to a region">
          {REGIONS.map((region) => {
            const isCurrent = region.id === currentRegion?.id;
            return (
              <button
                key={region.id}
                type="button"
                className={`region-button${isCurrent ? " is-current" : ""}`}
                aria-pressed={isCurrent}
                onClick={() => flyToRegion(region)}
              >
                {region.label}
              </button>
            );
          })}
        </div>

        <div className="panel-title">Layers</div>
        {LAYERS.map((layer) => {
          const info = meta[layer.name];
          const on = enabled[layer.name];
          const zoomedOut = !layerVisibleAtZoom(layer.name, zoom);
          return (
            <label key={layer.name} className={`row${on && !zoomedOut ? "" : " off"}`}>
              <input
                type="checkbox"
                checked={on}
                onChange={(event) =>
                  setEnabled((previous) => ({
                    ...previous,
                    [layer.name]: event.target.checked,
                  }))
                }
              />
              <span className="swatch" style={{ background: `var(--map-${layer.name})` }} />
              {layer.label}
              <span className="count">
                {on && zoomedOut
                  ? `z${MIN_ZOOM_FOR_LINEWORK}+`
                  : on && info
                    ? `${info.returned.toLocaleString()}${info.truncated ? ` / ${info.matched.toLocaleString()}` : ""}`
                    : ""}
              </span>
            </label>
          );
        })}
        {loading ? (
          <div className="status">
            <span className="spinner" />
            Loading…
          </div>
        ) : (
          fromCache && <div className="status cached">Cached · zoom {zoom.toFixed(1)}</div>
        )}
      </div>

      {session && (
        <div className="panel saved-panel">
          <div className="panel-title">Saved</div>
          {saved.length === 0 ? (
            <div className="saved-empty">
              Nothing saved yet. Open a campsite and choose Save.
            </div>
          ) : (
            <ul className="saved-list">
              {saved.map((campsite) => (
                <li key={campsite.id}>
                  <button
                    type="button"
                    className="saved-row"
                    onClick={() => flyToSaved(campsite)}
                    title="Show on the map"
                  >
                    {campsite.name}
                  </button>
                  <button
                    type="button"
                    className="saved-remove"
                    onClick={() => void toggleSaved(campsite)}
                    aria-label={`Unsave ${campsite.name}`}
                    title="Unsave"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          {/* TODO(TM05-32): this list is what *this browser* saved, not what the
              account holds -- the accounts API has no GET /api/saved-campsites/ yet.
              It is empty on another device and does not reflect a save made
              elsewhere. Replace with a fetch once that story lands. */}
          <div className="saved-caveat">Showing saves made in this browser.</div>
        </div>
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

/**
 * Campsite popup.
 *
 * reservable and capacity are tri-state per docs/api.md: null means the source did not
 * say, which is different from false. Rendering a null as "Not reservable" would be
 * asserting something we do not know.
 */
function campsitePopup(properties: Record<string, unknown> | null): string {
  const name = (properties?.name as string) || "Unnamed campsite";
  const siteType = ((properties?.site_type as string) ?? "unknown").replace(/_/g, " ");

  const reservable = properties?.reservable;
  const capacity = properties?.capacity;

  // A value the source did not give us is styled as unknown rather than rendered as a
  // fact -- null means "not recorded", which is not the same as "no".
  const row = (label: string, value: string, unknown: boolean, numeric = false) => {
    const classes = [unknown ? "unknown" : "", numeric && !unknown ? "numeric" : ""]
      .filter(Boolean)
      .join(" ");
    return `<dt>${label}</dt><dd${classes ? ` class="${classes}"` : ""}>${escapeHtml(value)}</dd>`;
  };

  return `
    <div class="popup">
      <div class="popup-eyebrow">Campsite</div>
      <h3 class="popup-title">${escapeHtml(name)}</h3>
      <dl>
        ${row("Type", siteType, siteType === "unknown")}
        ${row(
          "Reservable",
          reservable === true ? "Yes" : reservable === false ? "No" : "Unknown",
          reservable !== true && reservable !== false,
        )}
        ${row(
          "Capacity",
          capacity === null || capacity === undefined ? "Unknown" : `${capacity} people`,
          capacity === null || capacity === undefined,
          true,
        )}
      </dl>
    </div>`;
}

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ]!,
  );
}
