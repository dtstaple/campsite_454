import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export default function App() {
  const mapContainer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mapContainer.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: "https://demotiles.maplibre.org/style.json",
      center: [-76.15, 43.05],
      zoom: 9,
    });

    map.addControl(new maplibregl.NavigationControl());

    return () => map.remove();
  }, []);

  console.log("API base URL configured as:", API_BASE_URL);

  return <div ref={mapContainer} style={{ width: "100vw", height: "100vh" }} />;
}