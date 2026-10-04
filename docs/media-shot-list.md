# Homepage media shot list (TM05-68)

The homepage (`frontend/src/pages/Landing.tsx`) has four media slots. Until a file exists,
each slot shows a placeholder saying what to record, so the page never looks broken. When
a file arrives it drops into the same 16:10 frame, so nothing on the page moves.

All four clips use the **Van Hoevenberg Trail** (Adirondacks, OSM relation 6619234,
7.7 mi). It has a working elevation profile and four campsites along it, so every shot
below is possible with today's data.

## Files

Put them in `frontend/public/media/`:

| Slot | Video | Poster |
|---|---|---|
| Hero | `hero.mp4` | `hero-poster.jpg` |
| Preview the route | `route-preview.mp4` | `route-preview-poster.jpg` |
| Campsites along the trail | `campsites-along-trail.mp4` | `campsites-along-trail-poster.jpg` |
| What's behind a score | `site-score.mp4` | `site-score-poster.jpg` |

## Setup for every clip

- **Window.** Chrome with a **1440 × 900 viewport**, which is 16:10, the frame's shape.
  - Set it in DevTools → device toolbar → Responsive, 1440 × 900, zoom 100%, then close
    the toolbar.
  - Or size the window until `innerWidth × innerHeight` in the console reads 1440 × 900.
- **What to capture.** Record only the viewport, not the browser chrome. On macOS:
  Cmd-Shift-5 → Record Selected Portion, dragged to the page area.
- **App state.** Run the backend and frontend (docs/setup.md) and open
  `http://localhost:5173/discover`. Be signed out,
  so no personal saved sites show. Use the **Hiking** mode.
- **The pointer.** Move it slowly and deliberately, with no stray hovering. Start and end
  each clip on a similar frame so the loop is not jarring.
- **Length.** Every clip is **6–10 s** and loops cleanly.
- **Size.** Every clip is **≤ 3 MB** after conversion (below).

## The shots

### 1. Hero: 3D flythrough (`hero.mp4`, ~8 s)

1. Choose the Adirondacks region, zoom to Adirondak Loj / Heart Lake (south of Lake
   Placid), and click the Van Hoevenberg Trail, the named route running south-east to
   Marcy.
2. Basemap: **Satellite** (bottom left).
3. Press **3D**, then **▶ Fly the trail**.
4. Record about 8 s of the camera climbing from Marcy Dam toward the summit.

- **Camera motion:** the flythrough's own camera. Don't touch the mouse.
- **Loop:** cut at two points where the camera is moving in the same direction, so the
  jump reads as one continuous glide.

### 2. Preview the route (`route-preview.mp4`, ~9 s)

1. Van Hoevenberg Trail selected, standard (Map) basemap, 2D, with the trail panel open.
2. Move the pointer slowly along the elevation profile, from the trailhead to about the
   midpoint. The marker on the map follows (about 4 s).
3. Press **3D**. The map tilts and the terrain rises (about 2 s).
4. Press **▶ Fly the trail** and let it run for about 3 s.

- **Camera motion:** static in 2D, then the app's own tilt and flythrough.
- **Loop:** end by pressing **3D** off, or cut just before the tilt starts again.

### 3. Campsites along the trail (`campsites-along-trail.mp4`, ~8 s)

1. Van Hoevenberg Trail selected, standard basemap, 2D. Scroll the trail panel so the
   **Campsites along this trail** list shows. It holds four sites:
   - mi 0.0, Wilderness Campground at Heart Lake
   - mi 2.3, Marcy Dam Backcountry Campsites
   - mi 3.0 and mi 3.1, two unnamed sites
2. Hover each site from top to bottom, about 1.5 s each. The profile cursor jumps to that
   mile.
3. Click **Marcy Dam Backcountry Campsites**. The map flies to it.

- **Camera motion:** static, then the app's fly-to.
- **"within" control:** don't change it in this clip. On this trail the list is the same
  four sites at every setting from 250 m to 2 km, so the change would show nothing.

### 4. What's behind a score (`site-score.mp4`, ~7 s)

1. From the Van Hoevenberg list, click **Marcy Dam Backcountry Campsites**. Its score
   reads **99** in the list.
2. The campsite panel opens. Rest the pointer on each row in turn for about 1 s:
   - public land
   - slope
   - nearest water
   - nearest trail
3. End on the whole panel.

- **Basemap:** Satellite reads well behind the site, but either works.
- **Camera motion:** the app's fly-to, then static.
- **Breakdown:** the per-factor score breakdown is TM05-47 and not in the UI yet. Don't
  stage or mock one. If TM05-47 lands first, re-record this clip with the breakdown
  showing.

## Converting a recording

Scale to 1600 px wide at 30 fps, as H.264 with no audio, with the `moov` atom first so
playback starts before the download finishes:

```
ffmpeg -i in.mov -vf "scale=1600:-2,fps=30" -c:v libx264 \
  -crf 26 -preset slow -an -movflags +faststart out.mp4
```

The poster is the first frame:

```
ffmpeg -i out.mp4 -frames:v 1 -q:v 3 out-poster.jpg
```

Rename the pair to the slot's names above.

**Check the size:** `ls -lh out.mp4` should be ≤ 3 MB.

- If it isn't, raise `-crf` by 2 at a time; 28–30 still looks clean for UI footage.
- Or trim with `-t 8` after `-i in.mov`.
- As a reference, a 6 s synthetic test pattern with constant motion came out at 1.5 MB with
  these settings. Real UI footage, which is mostly static, is usually smaller.

## How the page uses them

`frontend/src/home/FeatureMedia.tsx`:

- **Loading.** Nothing loads until a slot is within one screen of view. The slot then
  checks the file really is a video (a missing file in `public/` gets the app's
  `index.html` back, not a 404).
- **Playback.** Videos play muted and looped, with a Pause button.
- **Reduced motion.** With *prefers-reduced-motion*, the poster shows with a Play button
  and nothing autoplays.
