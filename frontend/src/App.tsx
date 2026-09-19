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
import type { FeatureCollection as GeoJsonFeatureCollection } from "geojson";
import {
  ApiError,
  fetchLayer,
  simplifyForZoom,
  type Bbox,
  type LayerName,
  type Metadata,
} from "./api";

// The Adirondacks: where the ingested data actually is.
const ADIRONDACKS: [number, number] = [-74.2, 44.1];
const INITIAL_ZOOM = 10;
const DEBOUNCE_MS = 400;

const LAYERS: { name: LayerName; label: string; colour: string }[] = [
  { name: "water", label: "Water", colour: "#2b7fd4" },
  { name: "trails", label: "Trails", colour: "#a2571a" },
  { name: "campsites", label: "Campsites", colour: "#1f9d55" },
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

  /** Fetch every enabled layer for the current viewport and push it into the map. */
  const refresh = useCallback(async () => {
    const current = map.current;
    if (!current || !styleReady.current) return;

    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    const bbox = current.getBounds().toArray().flat() as Bbox;
    const simplify = simplifyForZoom(current.getZoom());

    setLoading(true);
    setError(null);

    const active = LAYERS.filter((layer) => enabledRef.current[layer.name]);
    // Clear any layer that has just been toggled off.
    for (const layer of LAYERS) {
      if (!enabledRef.current[layer.name]) {
        (current.getSource(layer.name) as maplibregl.GeoJSONSource | undefined)?.setData(
          EMPTY,
        );
        setMeta((previous) => ({ ...previous, [layer.name]: undefined }));
      }
    }

    try {
      const results = await Promise.all(
        active.map((layer) =>
          fetchLayer(layer.name, bbox, simplify, controller.signal).then((collection) => ({
            layer: layer.name,
            collection,
          })),
        ),
      );
      if (controller.signal.aborted) return;

      for (const { layer, collection } of results) {
        const source = current.getSource(layer) as maplibregl.GeoJSONSource | undefined;
        source?.setData(collection as unknown as GeoJsonFeatureCollection);
        setMeta((previous) => ({ ...previous, [layer]: collection.metadata }));
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
      style: "https://demotiles.maplibre.org/style.json",
      center: ADIRONDACKS,
      zoom: INITIAL_ZOOM,
    });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl(), "top-right");

    instance.on("load", () => {
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
        paint: { "fill-color": "#2b7fd4", "fill-opacity": 0.45 },
      });
      instance.addLayer({
        id: "water-line",
        type: "line",
        source: "water",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": "#2b7fd4", "line-width": 1.2 },
      });

      instance.addLayer({
        id: "trails-line",
        type: "line",
        source: "trails",
        paint: { "line-color": "#a2571a", "line-width": 1.6 },
      });

      instance.addLayer({
        id: "campsites-point",
        type: "circle",
        source: "campsites",
        paint: {
          "circle-radius": 6,
          "circle-color": "#1f9d55",
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff",
        },
      });

      styleReady.current = true;
      void refresh();
    });

    // Refetch when the viewport settles, debounced so a drag is one request.
    const onIdle = () => {
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
        <strong>CampSite prototype</strong>
        {LAYERS.map((layer) => {
          const info = meta[layer.name];
          return (
            <label key={layer.name} className="row">
              <input
                type="checkbox"
                checked={enabled[layer.name]}
                onChange={(event) =>
                  setEnabled((previous) => ({
                    ...previous,
                    [layer.name]: event.target.checked,
                  }))
                }
              />
              <span className="swatch" style={{ background: layer.colour }} />
              {layer.label}
              <span className="count">
                {enabled[layer.name] && info
                  ? `${info.returned}${info.truncated ? ` / ${info.matched}` : ""}`
                  : ""}
              </span>
            </label>
          );
        })}
        {loading && <div className="status loading">Loading…</div>}
      </div>

      {error && <div className="banner error">{error}</div>}

      {truncated.length > 0 && !error && (
        <div className="banner warn">
          Zoom in to see all features — showing{" "}
          {truncated
            .map((layer) => {
              const info = meta[layer.name]!;
              return `${info.returned.toLocaleString()} of ${info.matched.toLocaleString()} ${layer.label.toLowerCase()}`;
            })
            .join(", ")}
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
  const siteType = (properties?.site_type as string) ?? "unknown";

  const reservable = properties?.reservable;
  const reservableText =
    reservable === true ? "Yes" : reservable === false ? "No" : "Unknown";

  const capacity = properties?.capacity;
  const capacityText =
    capacity === null || capacity === undefined ? "Unknown" : `${capacity} people`;

  return `
    <div class="popup">
      <h3>${escapeHtml(name)}</h3>
      <dl>
        <dt>Type</dt><dd>${escapeHtml(siteType.replace(/_/g, " "))}</dd>
        <dt>Reservable</dt><dd>${reservableText}</dd>
        <dt>Capacity</dt><dd>${escapeHtml(capacityText)}</dd>
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
