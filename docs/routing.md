# Routing across connected trails (TM05-119)

A real trip uses more than one trail. CampSite builds a routable graph from the trail
network's shared OSM junction nodes, and routes between points a user picks on the map,
through any stops in between, in order. The result opens in the trail panel like any
trail, so Find campsites, + Night, the overnight plan's daily distances and the GPX
export all work on it.

| Piece | Where |
|---|---|
| Graph build | `backend/routing/build.py`, `manage.py build_trail_graph <region>` |
| Stored graph | `routing.TrailEdge`, `routing.TrailGraphBuild` (`backend/routing/models.py`) |
| **Engine** (the replaceable part) | `backend/routing/engine.py` |
| Snapping, route ids, assembly | `backend/routing/service.py` |
| API | `backend/routing/views.py`; contract in `docs/api.md`, "Planned routes" |
| UI | `frontend/src/routing/RoutePlanner.tsx`, opened in `trails/TrailInsight.tsx` |

## The graph

A `Trail` row is one OSM way, and its `osm_node_ids` line up with its vertices
(`docs/pipeline.md`). Two ways meet where they share a node.

- **Nodes** are OSM node ids: every node two ways share (or one way uses twice, for a
  loop), and every way's two ends.
- **Edges** are the stretch of one way between two consecutive nodes. Nothing joins or
  leaves an edge in between. Each edge is walkable both ways.
- **Length** is measured on the way's metre geometry (EPSG:5070, `geom_m`).
- **Climb.** Each edge is sampled every 50 m (and at both ends) from 3DEP. `ascent_m` is
  the sum of every rise between consecutive samples walking start to end, and `descent_m`
  every drop; the other way round they swap. At 50 m spacing that is already smoothed,
  and a per-edge threshold would lose the many small climbs of short edges. The samples
  are kept on the edge, so a route can start partway along it. The raster is never
  stored (CLAUDE.md: store derived results).
- **Ways whose node ids don't match their vertices** are skipped and counted. **Ways that
  only cross**, without sharing a node, do not meet, exactly as in OSM. Roads are not
  ingested (only paths, footways, tracks and bridleways), so routes never use them.

`build_trail_graph <region>` replaces the region's edges in one transaction and writes a
`TrailGraphBuild` with the counts, the 3DEP provenance and the timings. Run it after
`ingest osm-trails <region>`. The web process loads a region's graph once and reloads it
when a newer build exists.

## Costs

| Cost | Per edge | Use |
|---|---|---|
| `naismith` (default) | `length_m / (5000 / 3600) + ascent_m × 6` seconds | Quickest on foot |
| `distance` | `length_m` | Shortest |

Naismith's rule: 5 km/h on the flat, plus one hour for every 600 m of ascent. Descent
is free, as in the rule as Naismith gave it, so the cost is asymmetric: up a steep trail
is slow and down it is not. The trail panel's "Time" stat applies the same rule to the
profile's smoothed gain.

## The engine interface (for a C++ implementation)

`backend/routing/engine.py` is plain Python with no Django, database or geometry library.
A replacement implements the same contract; the Python side then only swaps the call in
`service._solve`.

### Input: the graph

```
nodes: id (int64)  ->  (x, y) in metres, any planar projection (CampSite uses EPSG:5070)
edges: id (int64), u (int64), v (int64), length_m (float64 > 0 or 0),
       ascent_m (float64 >= 0, climb walking u -> v), descent_m (float64 >= 0),
       factor (float64 >= 1, cost multiplier: 1 on trail, 1.5 on a road walk; TM05-137)
```

- Ids are opaque: the engine only hands them back. Node ids are OSM node ids, and
  **negative** ids are stops added between two junctions for one request.
- Every edge is undirected for walking; direction only swaps ascent and descent.
- The Adirondacks graph is 92,663 edges and 75,973 nodes since TM05-137 (see "Measured").
- `service.region_graph()` builds it from `EDGES_SQL`; the same rows are a natural file
  format (one row per edge, plus the endpoint coordinates).

### The call

```
route(graph, start: int64, end: int64, waypoints: list[int64], cost: "naismith" | "distance")
    -> Route
```

- Visit `waypoints` **in the order given**. Each leg (start -> w1, w1 -> w2, ..., wn ->
  end) is the least-cost path on its own, so a route may walk a stretch twice (out and
  back).
- `start == end` with waypoints is a loop; a leg from a node to itself is empty.

### Output: the route

```
Route:
  cost: str
  legs: [Leg]                      one per consecutive pair of stops
  expanded: int                    nodes settled by the search (for measuring)
Leg:
  start, end: int64
  steps: [Step]                    in walking order
Step:
  edge: int64, forward: bool       forward = walked u -> v
  from_node, to_node: int64
  length_m, ascent_m, descent_m    as walked (ascent/descent already swapped if backward)
```

Totals (`length_m`, `ascent_m`, `descent_m`, `naismith_s`) are sums over the steps.

### Errors

| Condition | Python | Meaning |
|---|---|---|
| A stop isn't in the graph | `RoutingError` | Bad request |
| Unknown cost | `RoutingError` | Bad request |
| Two consecutive stops not connected | `NoRoute(start, end)` | The trails don't join |

### Required behaviour

Both costs are multiplied by the edge's `factor`. The answer must be the **true
least-cost path** for the cost. The Python engine uses A*
with an admissible heuristic: straight-line distance (divided by 5 km/h for `naismith`).
That never overestimates, since every edge is at least its chord, and ascent and a
factor of at least 1 only add. Ties may break differently between engines; costs must match to 1e-6.

`tests/test_routing_engine.py` holds the cases any engine has to pass: Naismith choosing
the long flat way over the short steep one, distance choosing the reverse, the
direction-swapped climb, waypoint order, out-and-back, an unconnected node, unknown
nodes and costs, and an empty leg.

## Snapping and route ids

- **Clicks snap to the nearest point on a trail segment** (TM05-137): the click is
  projected onto each nearby trail or track edge (`snapping.radius_m`, 1 km). The stop is
  that point, not the nearest vertex. Roads and bridges are never snapped to.
- **One connected piece for the whole request.** Each click keeps the nearest edge of
  every connected piece within reach, and the piece chosen is the one all clicks reach at
  the least total distance. A piece with under `fragment_max_km` (2 km) of trail counts
  `fragment_penalty_m` (300 m) extra, so a main-network trail nearby beats a few paths
  round a lodge (`service.snap_all`). All clicks are found in one query (a `LATERAL` KNN
  join ordered by `<->`).
- **When no piece is shared,** the error names the nearest point where a connected route
  is possible: the node of one stop's network nearest the other stop. The 422 response
  carries it as `suggestion`, and the planner offers "Start on ... instead".
- **A stop between two junctions** becomes a node for that one request. Its edge is split
  there, with each part's length from the geometry and its climb from the stored samples.
- **A planned route's id** is what the user chose: `<region>:<cost>:<stop>,<stop>,...`
  (start, stops in order, end). A stop is `w<way>-<decimetres>`, a point that far along
  OSM trail way `<way>`, or an OSM node id for a stop exactly at a junction. TM05-119's
  ids, all node ids, still resolve. Both kinds survive a rebuild, so a saved plan or a
  shared link solves to the same route while the trails are unchanged. Re-solving takes
  milliseconds once the graph is loaded, so nothing else is stored.
- **The route becomes an unsaved `TrailRoute`**, like an assembled trail (TM05-97): one
  ordered line, `member_way_ids` for every trail way used, `source_id` `planned/<digest>`.
  `route_detail`, the candidate search, `build_plan` and `route_gpx` take it unchanged.
- **Overnight plans** store the route id in `TripPlan.planned_route` (migration
  `planning.0006`).

## Forgiving connections (TM05-137)

**The bug.** A start at 43.8545, -73.8067 and an end at 44.0558, -73.8824 failed: "No
connected trails join these points: Big Pond Trail / Pinnacle Ridge Trail".

**Diagnosis** (graph before TM05-137):
- **The network was fragmented:** 5,274 connected pieces. The largest held 5.1% of
  nodes and 7.3% of trail length (813 of 11,154 km), and 3,355 pieces were a single way.
- **The start was on a separate 49-node piece.** It was the Big Pond, Jones Hill and
  Hoffman Notch trails (42 km), the only trails within 400 m of the click. The end was on
  the main network.
- **In OSM the two are connected, by about 70 m of road** that the trail ingest leaves
  out:
  - the Hoffman Notch Trail ends at node 212039408, on **Blue Ridge Road**
    (`highway=secondary`, way 1394407171)
  - Blue Ridge Road meets **Branch Road** (`highway=service`, `service=driveway`, gravel,
    way 810350485) at node 7576366751
  - Branch Road reaches node 7576366752, where the main network's "Branch Road" path
    begins
- **No near-miss and no shared trail node was involved.** It was a road the trail
  filter removed.

**What the build adds** (`backend/routing/build.py`, settings in
`backend/routing/routing.yml`):

| Edge kind | What | Cost | Shown as |
|---|---|---|---|
| `trail` | path, footway, bridleway ways | 1× | the trail's name |
| `track` | `highway=track` ways (already trails) | 1× | "track" |
| `road` | `geodata.Connector` roads and sidewalks within `connectors.max_from_trail_m` (1 km) of a trail, by road | `connectors.cost_factor` (1.5×) | "road walk" |
| `bridge` | a trail's loose end to the nearest point on another trail or road, within `build.bridge_tolerance_m` (15 m) | 1× | "gap bridged" |

- **Roads** come from the new `osm-connectors` source (`docs/pipeline.md`):
  - secondary, tertiary, unclassified, residential, living_street and service roads, plus
    the sidewalks and crossings the trail filter drops
  - never primary, trunk, motorway, `access=private|no` or `foot=no`
  - a `service=driveway` is kept only where it shares a node with a trail, as that trail's
    access from the road: the Branch Road case

  Road edges further than 1 km by road from every trail are dropped, so a road walk
  between two trails is at most about 2 km.
- **Crossings.** Two trails that cross with no shared node get one at the crossing,
  unless either is tagged `bridge`, `tunnel` or `layer`.
- **Added nodes.** Bridge ends and crossings get deterministic ids, `SYNTHETIC_BASE`
  (5 × 10¹⁵) plus the point's decimetre coordinates, so a rebuild reproduces them.
- **Elevation is reused.** A rebuild reads each way's elevation from the previous build's
  samples by distance along the way, so only new ways go to 3DEP.

## Measured (dev DB, 2026-10-23)

### TM05-137, before and after

| | Before | After |
|---|---|---|
| Ways in the build | 18,067 | 76,355 (+58,288 roads and sidewalks) |
| Edges / nodes | 29,077 / 30,854 | 92,663 / 75,973 (22,216 trail, 8,277 track, 59,876 road, 2,294 bridge) |
| Connected pieces | 5,274 | 2,555 |
| Largest piece | 813 km (7.3% of length, 5.1% of nodes) | 1,771 km (10.1% of 17,557 km incl. roads, 6.8% of nodes) |
| 50 random trips, 5–30 km, on named trails across the park (seed 137) | 11 routed (22%) | 21 routed (42%) |
| ...of them, both ends within 1 km of the main network | – | 18 of 18 (100%) |
| Reproduction case | fails | routes: 34.0 km, Big Pond Trail to Pinnacle Ridge via Blue Ridge Road and Branch Road |
| Graph load, once per process (cold) | 0.41 s | 0.93 s |

- **Before:** `ingest osm-trails` plus the TM05-119 build, 1,220.7 s (3DEP 1,205.0 s).
- **After:**
  - `ingest osm-connectors adirondacks`: 70,773 roads and sidewalks in 14.2 min
    (Overpass, 0.5° tiles).
  - First build with roads: 895.0 s, all trail edges reusing their samples and 216,761
    new samples for the roads.
  - Each rebuild since: 107–128 s, with 0 to 4,769 new samples.

**Routing**, by Naismith time, warm (graph loaded, median of five runs) and cold (a fresh
process):

| Trip | Before warm | After warm | After cold |
|---|---|---|---|
| Reproduction case (Big Pond → Pinnacle Ridge) | fails | 13.3 ms | 758 ms |
| Adirondak Loj → Marcy → Phelps Mountain → Loj | 126.9 ms | 18.1 ms | 779 ms |
| Upper Works → Lake Colden → Marcy → The Garden | 112.4 ms | 28.6 ms | 821 ms |
| Hoffman Notch Trail (Blue Ridge Road) → Marcy | 65.8 ms | 13.5 ms | 818 ms |

What made warm routing 4–7× faster although the graph is three times bigger:
1. **One coordinate transformation per process.** `geom.transform(srid)` builds a new
   PROJ transformation every call, at about 15 ms each, which was most of a request.
2. **A layered graph copy.** Each request's few extra nodes sit on a `ChainMap` over the
   region's graph, instead of copying its ~170,000 entries.
3. **One KNN query for all clicks.** It loads edges without their samples, and assembly
   loads only the fields it uses.

Cold requests are slower because the graph is bigger. That is once per web process.

**Failures that remain** (10 of the 29 sampled, during the time-boxed tuning):
- **7 are separate trail systems,** 5.9 to 25 km from any network they could join.
- **2 are the Saint Regis Mountain piece and the Adirondack Rail Trail.** They are
  1.5 km apart, but no trail or road links them within 6 km of the gap.
- **1 is Whiteface Landing and the Jackrabbit Trail,** 0.6 km apart across Lake Placid.
  The lake is between them; there is no land link.
- **None are snapping misses.**

### TM05-119 (the first graph)

- **Build:** 18,067 ways (0 skipped), 29,077 edges and 30,854 nodes, with 267,998
  elevation samples (0 no data), in 1,220.7 s. Cutting took 6.1 s and 3DEP 1,205.0 s.
- **Routing**, warm then cold, by Naismith time:
  - Loj → Marcy → Phelps Mountain → Loj (25.4 km): 106 ms, 473 ms
  - Loj → Algonquin → Lake Colden → Loj (20.4 km): 108 ms, 292 ms
  - Upper Works → Lake Colden → Marcy → The Garden (34.8 km): 110 ms, 277 ms

  The search itself took under 1 ms.

**Why snapping picks a connected piece.** At Adirondak Loj the nearest trails are a
13-node cluster of footways around the lodge that joins nothing else. Snapping each
click on its own sent the route from there, and it could never reach Marcy. So every
click lists the edges within 400 m, the piece chosen is the one all clicks have an edge
in (least total distance), and each click snaps to its nearest vertex on that piece
(`service.snap_all`).

**In the browser** (headless Chrome, 1440 × 900 and 390 × 844): Loj → Marcy → Phelps
Mountain → Loj planned from four map clicks; its profile and stats; Find campsites (8
mapped, 8 potential); two lean-tos as nights with daily distances; and a GPX of 2,106
track points and 8 waypoints. Screenshots are in `artifacts/sprint7/`.

## Known limits

- **A route that walks the same stretch twice** (out and back, or a lollipop) has an
  ambiguous mile there. The campsite list, candidates and nights locate a site on the
  nearest point of the line (`ST_LineLocatePoint`), which is its first pass.
- **Saved trails and hikes** (TM05-100, TM05-111) keep a trail by route or way only. A
  planned route can be planned, saved as an overnight plan and exported, but not saved
  as a trail or hiked in trail mode; the panel hides those two buttons for it.
- **Graph ascent vs profile gain.** The panel's stats come from the route's 3DEP profile
  (25 m, smoothed, 3 m threshold), the same as any trail. The graph's own totals (50 m,
  unsmoothed sum) drive the cost and are reported in `planned.graph_totals`; they differ
  slightly.
