/**
 * Throwaway prototype to prove the TM05-14 render path end to end.
 *
 * Not the real TM05-15 implementation -- see the notes at the bottom of the handover
 * message for what would need to change. Everything here follows docs/api.md.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "./App.css";
import { mapColors, mapPaint } from "./theme";
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
} from "./api";

/*
 * Basemap. Stadia's "Alidade Smooth Dark" serves keyless from allowlisted domains
 * including localhost, verified against the live endpoint. Read from env so a key
 * can be appended for a deployed domain without touching code.
 */
const MAP_STYLE_URL =
  import.meta.env.VITE_MAP_STYLE_URL ??
  "https://tiles.stadiamaps.com/styles/alidade_smooth_dark.json";

// The Adirondacks: where the ingested data actually is.
const ADIRONDACKS: [number, number] = [-74.2, 44.1];
const INITIAL_ZOOM = 10;
const DEBOUNCE_MS = 400;

const LAYERS: { name: LayerName; label: string }[] = [
  { name: "water", label: "Water" },
  { name: "trails", label: "Trails" },
  { name: "campsites", label: "Campsites" },
];

const EMPTY: GeoJsonFeatureCollection = { type: "FeatureCollection", features: [] };

export default function App() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const styleReady = useRef(false);
  const inFlight = useRef<AbortController | null>(null);
  const debounce = useRef<number | undefined>(undefined);

  const [enabled, setEnabled] = useState<Record<LayerName, boolean>>({
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

  const [zoom, setZoom] = useState(INITIAL_ZOOM);
  const [fromCache, setFromCache] = useState(false);

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

  // --- map setup, once ------------------------------------------------------------

  useEffect(() => {
    if (!mapContainer.current) return;

    const instance = new maplibregl.Map({
      container: mapContainer.current,
      style: MAP_STYLE_URL,
      center: ADIRONDACKS,
      zoom: INITIAL_ZOOM,
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
      window.clearTimeout(debounce.current);
      debounce.current = window.setTimeout(() => void refresh(), DEBOUNCE_MS);
    };
    instance.on("moveend", onIdle);
    instance.on("zoomend", onIdle);

    // Campsite popups.
    instance.on("click", "campsites-point", (event: maplibregl.MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;
      new maplibregl.Popup({ closeButton: true })
        .setLngLat(event.lngLat)
        .setHTML(campsitePopup(feature.properties))
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
  }, [refresh]);

  // Toggling a layer refetches rather than hiding, so a layer turned back on is current.
  useEffect(() => {
    void refresh();
  }, [enabled, refresh]);

  const truncated = LAYERS.filter((layer) => meta[layer.name]?.truncated);

  return (
    <div className="app">
      <div ref={mapContainer} className="map" />

      <div className="panel">
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
