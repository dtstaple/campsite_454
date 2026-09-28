import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

/*
 * Vendor stylesheets first, ours after, and this is the only place that decides.
 *
 * MapLibre puts `maplibregl-map` on the container element we already class as `map`,
 * and both `.map { position: absolute }` and `.maplibregl-map { position: relative }`
 * are single-class selectors. Specificity ties, so whichever stylesheet is emitted last
 * wins. When App.tsx owned the map it imported these two in this order by accident and
 * ours won; once App.tsx became the router shell, maplibre-gl.css moved to Discover.tsx
 * and started landing *after* App.css. `.map` lost, the container fell back to
 * `position: relative`, `inset: 0` stopped meaning anything, and it collapsed to zero
 * height -- a black void with the panels floating over it.
 *
 * Importing vendor CSS here, above './index.css' and the App tree, makes the order
 * explicit rather than a side effect of which component happens to import what.
 */
import 'maplibre-gl/dist/maplibre-gl.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
