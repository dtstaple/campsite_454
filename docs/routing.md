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
       ascent_m (float64 >= 0, climb walking u -> v), descent_m (float64 >= 0)
```

- Ids are opaque: the engine only hands them back. Node ids are OSM node ids, and
  **negative** ids are stops added between two junctions for one request.
- Every edge is undirected for walking; direction only swaps ascent and descent.
- The graph for a region is about 50,000 edges (see "Measured").
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

The answer must be the **true least-cost path** for the cost. The Python engine uses A*
with an admissible heuristic: straight-line distance (divided by 5 km/h for `naismith`).
That never overestimates, since every edge is at least its chord and ascent costs only
add. Ties may break differently between engines; costs must match to 1e-6.

`tests/test_routing_engine.py` holds the cases any engine has to pass: Naismith choosing
the long flat way over the short steep one, distance choosing the reverse, the
direction-swapped climb, waypoint order, out-and-back, an unconnected node, unknown
nodes and costs, and an empty leg.

## Snapping and route ids

- **Clicks snap** to the nearest trail **vertex** within 400 m (KNN on `TrailEdge.geom_m`).
  Every vertex has an OSM node id, so a stop is always a node id.
- **A stop between two junctions** becomes a node for that one request. Its edge is split
  there, with each part's length from the geometry and its climb from the stored samples.
- **A planned route's id** is what the user chose: `<region>:<cost>:<node>,<node>,...`
  (start, stops in order, end). OSM node ids survive a rebuild, so a saved plan or a
  shared link solves to the same route while the trails are unchanged. Re-solving is
  milliseconds once the graph is loaded, so nothing else is stored.
- **The route becomes an unsaved `TrailRoute`**, like an assembled trail (TM05-97): one
  ordered line, `member_way_ids` for every way used, `source_id` `planned/<digest>`.
  `route_detail`, the candidate search, `build_plan` and `route_gpx` take it unchanged.
- **Overnight plans** store the route id in `TripPlan.planned_route` (migration
  `planning.0006`).

## Measured (dev DB, 2026-10-23)

**Graph build**, `build_trail_graph adirondacks`:

| | |
|---|---|
| Ways | 18,067 (0 skipped) |
| Edges | 29,077 |
| Nodes | 30,854 |
| Connected pieces | 5,274; the largest (the High Peaks network) has 1,562 nodes |
| Elevation samples | 267,998, 0 with no data |
| Time | 1,220.7 s: cutting 6.1 s, 3DEP 1,205.0 s (4 concurrent requests; two 502s retried) |

**Routing**, three Adirondack trips by Naismith time, five warm runs (median).

- **Cold:** the first request in a fresh process, which loads the graph.
- **Warm:** the graph is already loaded.
- **Detail:** the whole trail-panel payload (profile, campsites along, rating). Its first
  call fetches the route's 3DEP profile; after that it is cached.

| Trip | Distance | Climb (graph) | Naismith | Route, cold | Route, warm | Detail, first / cached |
|---|---|---|---|---|---|---|
| Adirondak Loj → Mount Marcy → Phelps Mountain → Loj | 25.4 km | 1,570 m | 7.7 h | 473 ms | 106 ms | 6.4 s / 0.32 s |
| Loj → Algonquin Peak → Lake Colden → Loj | 20.4 km | 1,228 m | 6.1 h | 292 ms | 108 ms | 3.9 s / 0.23 s |
| Upper Works → Lake Colden → Mount Marcy → The Garden | 34.8 km | 1,563 m | 9.6 h | 277 ms | 110 ms | 9.8 s / 0.82 s |

- **The search itself is under 1 ms** (517 to 642 nodes settled).
- **A cold request spends about 0.19 s loading the graph.**
- **The warm time is mostly the snapping queries** (about 70 ms for four clicks, each
  listing up to 40 nearby edges) and assembling the line (about 27 ms).
- **The graph's climb runs 8 to 12% above the profile's smoothed gain** (1,448 / 1,131 /
  1,401 m). The graph sums every rise between 50 m samples; the profile smooths over 100 m
  and ignores changes under 3 m.

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
