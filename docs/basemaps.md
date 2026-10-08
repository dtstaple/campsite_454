# Basemaps (TM05-65)

The map has two basemaps, switched by the floating **Map / Satellite** toggle at the bottom
left. The toggle is available in every activity mode, and the choice is remembered in
`localStorage` (`campsite.basemap`).

| Basemap | Source | Key |
|---|---|---|
| Map (standard) | Stadia Maps, Alidade Smooth Dark (vector) | none on localhost |
| Satellite | Esri World Imagery (raster) | none |

Code: `frontend/src/basemap/` (`satellite.ts`, `SatelliteLayers.tsx`, `BasemapToggle.tsx`,
`useBasemap.ts`).

## Esri World Imagery: verification record

Verified with `curl` over the Adirondacks on 2026-10-02, before any code used it.

```
https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}
```

- **Tile order is `{z}/{y}/{x}`**: row before column, unlike most XYZ services.
- **Real JPEG tiles through zoom 19** at every point sampled: Marcy, Lake Placid, a remote
  interior point (zooms 13–19, 21 tiles, all different), and 20 random points across the
  Adirondack box (zooms 18 and 19, 40 tiles, none of them the placeholder). That's 61
  real `200 image/jpeg` tiles.
- **From zoom 20 up, a placeholder.** Esri answers `200 image/jpeg` with the same
  2,521-byte grey tile reading "Map data not yet available" (MD5 `f27d9de7…`) at all three
  fixed points. The status alone can't detect it, so the source sets **`maxzoom: 19`** and
  MapLibre overzooms the zoom-19 tile instead of drawing grey squares.
- **Resolution.** The service describes its US imagery as 0.5 m. Zoom 19 is ~0.21 m per
  pixel at this latitude, so z19 is upsampled and looks slightly soft; z18 (~0.43 m) is
  close to native.
- **`tileSize: 256`**, matching Esri's tiles. Declaring 512 would make MapLibre request a
  zoom level lower than the screen needs, which is exactly what makes imagery blurry when
  pitched in 3D.

### Attribution

This is the service's own `copyrightText`, shown verbatim in the map attribution and linked
to the service's terms page:

> Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community

### Terms of use (note, not legal advice)

The service metadata links its terms at <https://goto.arcgisonline.com/maps/World_Imagery>.
**I have not verified the full legal text.**

My understanding is that Esri's basemap services are licensed under Esri's terms of use.
Keyless tile access like this is commonly used for non-commercial, educational and
evaluation work, provided the attribution above is displayed. It comes with no service
guarantee, and production or commercial use requires an ArcGIS account under Esri's
platform terms.

For a non-commercial student project that seems appropriate. Read the linked terms before
any public deployment, and move to an ArcGIS Location Platform key if the app is ever
deployed beyond the course.

## How satellite is drawn

- **Layer order.** The imagery is a raster layer placed **beneath the basemap's first label
  layer**. It covers the vector basemap's fills and roads, keeps its place names on top, and
  sits below every CampSite data layer. Once contour lines exist (TM05-83), the imagery goes beneath them
  instead, so the contours draw over it. See docs/terrain.md.
- **No hillshade over imagery.** Imagery already contains real shadows, and shading on top
  reads as mud. With satellite on, the hillshade is hidden. Turning satellite off restores
  whatever the Terrain shading toggle says.
- **3D.** Terrain (TM05-62) drapes the imagery automatically.
- **Readability.** Imagery is busy, so:
  - **Brightness and saturation.** The imagery is capped at `--map-imagery-brightness-max`
    (0.85) and desaturated slightly (`--map-imagery-saturation`, −0.1).
  - **Casings.** Trails and streams get a **dark casing that exists only over imagery**:
    `--map-casing-imagery`, opacity 0.75, 2.4 px wider than the line, added beneath
    `trails-line` and `water-line` without editing `map/layers.ts`.
  - **What already reads well.** Campsites already have a light stroke, and the selected
    route already has a casing.

## Measured (headless Chrome, live backend)

- Selecting Satellite stored the preference, and after a reload Satellite was still active.
- 191 imagery tiles loaded across a 2D view and a 3D flight to Marcy's summit cone. All 191
  returned 200, and there were no page exceptions.
