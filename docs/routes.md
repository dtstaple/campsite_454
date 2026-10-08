# Route difficulty, route type and campsites past the ends (TM05-82, TM05-73)

The trail panel and `GET /api/routes/<osm_id>/` describe each named route with a
**difficulty** and a **route type**.

- Code: `backend/geodata/route_rating.py`.
- Every threshold: `backend/geodata/routes.yml`.

## Difficulty

Shenandoah National Park's hiking rating, on the route's stored elevation profile:

```
rating = sqrt(climb_ft × 2 × distance_mi)
```

**Distance** is the route as mapped, one way.

**Climb** is the elevation gain in the route's **harder direction**, `max(gain, loss)`. A
route mapped downhill has a gain of 0, but it is just as hard walked the other way, and a
hiker may walk it either way. Franconia Brook Trail is the example: 0 ft of gain and
1,976 ft of loss as mapped, so it is rated on 1,976 ft.

| Label | Rating | Shenandoah's own bands, folded |
|---|---|---|
| Easy | below 50 | Easiest |
| Moderate | 50 to below 150 | Moderate, Moderately strenuous |
| Hard | 150 and up | Strenuous, Very strenuous |

Bands are `difficulty.bands` in `routes.yml`. With no profile (3DEP unavailable) the
difficulty is `null`; nothing is guessed.

**Examples (dev DB, 2026-10-07):**

| Route | Distance | Climb | Rating | Label |
|---|---|---|---|---|
| Van Hoevenberg Trail | 7.1 mi | 3,304 ft | 216 | Hard |
| Mount Marcy Trail | 4.1 mi | 2,616 ft | 147 | Moderate |
| Avalanche Pass Trail | 3.6 mi | 627 ft | 67 | Moderate |
| Calamity Brook – Indian Pass Crossover | 1.6 mi | 404 ft | 36 | Easy |

## Route type

### Loop: measured
If the start and end of the stitched route are within `loop_max_gap_m` (**200 m**) of each
other, it is a loop. This is a fact about the geometry, so `estimated: false`.

### Everything else: estimated
Each end is classified, checking these in order:

1. **summit:** the end is within `summit_within_m` (**15 m**, vertically) of the route's
   highest point, on a route that climbs at least `summit_min_relief_m` (**100 m**). The
   relief condition stops a flat route's ends counting as summits.
2. **connects:** another trail, not one of the route's own ways, is within `connect_m`
   (**30 m**).
3. **pond:** a lake or pond is within `pond_m` (**100 m**).
4. **dead_end:** none of the above.

A summit counts before connections: it is a destination even where other trails meet it,
as at Marcy. A connection counts before a pond: a junction at a lake is still a junction.

Then:

| The ends | Type |
|---|---|
| Either end is a summit or a pond | **Out & back.** You walk to it and back. |
| One end connects, the other dead-ends | **Out & back.** A spur to nowhere we can see. |
| Both connect, or both dead-end | **Point to point** |

All of these carry `estimated: true`. The panel shows "(est.)", and its tooltip says what
each end met.

### Known limitation: roads are not mapped
The database has trails and water, not roads. A trailhead on a road therefore reads as a
**dead end**. That is why two dead ends give point to point (both ends probably reach
roads). It also means a long through-route with a road at one end and a trail junction at
the other is called out & back: the **Northville-Placid Trail** is the visible case.
Ingesting trailheads (TM05-89) would let an end at a trailhead count as a connection.

### Measured over all 452 named routes (dev DB, 2026-10-07, 14 s)

| Type | Routes |
|---|---|
| Point to point (est.) | 260 |
| Out & back (est.) | 173 |
| Loop (measured) | 19 |

Most common end pairs: both connect (225); connects + dead end (134); both dead end (35);
connects + pond (20).

21 routes had a cached profile at measurement time: 14 Moderate, 5 Hard, 2 Easy. The rest
compute their profile, and so their difficulty, the first time the trail panel opens them.

## Campsites past a route's ends (TM05-73)

"Campsites along this trail" lists every site within the chosen distance of the route,
ordered by its nearest point on the stitched line. A site beyond either end has its
nearest point at the end itself. That used to read as "mi 0.0" for a site 763 m away
from the start, which is not a place on the trail.

### The rule

A site is **past an end** when both of these hold:

1. Its nearest point on the line is within `end_zone_m` (**50 m**) of the start or the
   end. A route's first segment is rarely straight, so a site off the end projects a few
   metres onto the line rather than exactly onto the end vertex: the Preston Ponds site
   lands 18 m along.
2. It is farther than `off_end_m` (**100 m**) from the line.

A site that is past an end gets `position` `near_start` or `near_end`, and
`position_label` "near the trailhead" or "near the trail's end". The trail list shows
"—" instead of a mile, with "near the trailhead · 763 m away" underneath. The profile
shows no marker for it, and hovering it moves no cursor.

Everything else is `along` and keeps its mile, including a site 60 m off the very start
of the trail. Both thresholds are under `along` in `routes.yml`.

The labels follow the line's direction: "trailhead" is the start of the stitched line,
which is not always the end hikers start from.

### Measured (dev DB, 2026-10-07)

Over all 452 named routes at the default 500 m, 869 sites are listed:

| Position | Sites |
|---|---|
| Along the trail (mile shown) | 574 |
| Near the trailhead | 140 |
| Near the trail's end | 155 |

Sites past an end appear on **67** routes. On Preston Ponds Trail (at 1 km), the site
763 m off and Henderson Lean-to (226 m off) both read "near the trailhead" now. The two
Duck Hole lean-tos keep miles 4.3 and 4.4.

## Named trails that are not route relations (TM05-97)

### The bug and its cause
In Hiking mode, clicking the **Adirondack Rail Trail** opened the old segment popup ("Type:
Path, Length 2.4 km") instead of the trail panel.

- **Not click priority, and not layer visibility.** The route click layer is
  `named-routes-hit`, and routes load from zoom 9, the same zoom trail linework appears.
  There was simply no route under the click.
- **The cause is route membership.**
  - The way (`way/20074658`) is `highway=path`, named "Adirondack Rail Trail", and none of
    its 55 ways is a member of any ingested TrailRoute.
  - In OpenStreetMap, its only relation is 1376439 "Adirondack Branch", which is
    `route=railway` (the old rail line). The route ingest correctly reads only
    `route=hiking`.
- **It is the common case, not an edge case.** In the Adirondacks, **3,652 of 4,494 named
  trail ways (81%) belong to no TrailRoute**: 2,153 distinct names, about 3,760 km.

### The fix: assemble a trail from mapped segments
`GET /api/trails/<way source_id>/trail/` (`backend/geodata/assembly.py`) returns the trail
panel's detail for a clicked way:

1. **A route member** returns its route: the longest named TrailRoute with that way as a
   member. `assembled: false`.
2. **A named way outside any route** returns a trail **assembled** from every way with the
   same name (case-insensitive) connected to it, through:
   - **shared OSM node ids** (`Trail.osm_node_ids`, preserved by the ingest for exactly
     this), or
   - **ends within 15 m** (`ENDPOINT_JOIN_M`).
3. **An unnamed way** returns 404. The map keeps its small popup.

Members are ordered by OSM id, so clicking any segment gives the same trail, the same
geometry and therefore the same **cached** elevation profile. The response is the route
detail's shape (profile, stats, difficulty, route type, campsites along), plus:
`assembled: true`, `osm_id: null`, `source_id: "assembled/way/<lowest id>"` and
`assembly: {from_way, ways, note: "Assembled from mapped segments"}`. The trail panel shows
that note under the name.

**Why the 15 m end join.** On shared nodes alone, the Rail Trail's 55 ways form **19**
groups. Mappers stopped ways a few metres short at road crossings and bridges, leaving gaps
of 4.7–12.7 m. With the 15 m join they form **7** groups. That is still well under the
50 m the profile stitching tolerates, and same-name only.

The remaining splits are real gaps in the data: 17 m, 23 m and 189 m. The 189 m gap
separates the 20.8 km and 16.9 km sections. They were left split rather than widening the
join.

### Measured (dev DB, 2026-10-07)

| Click | Ways | Length | Profile | Difficulty | Type |
|---|---|---|---|---|---|
| `way/20074658` (Rail Trail, Lake Clear section) | 7 | 20.8 km | first request 17 s (3DEP), then 0.5–0.9 s cached | Moderate | Point to point (est.) |
| `way/661913584` (Rail Trail, another section) | 17 | 12.0 km | 4.7 s | Moderate | Out & back (est.) |

The Lake Clear section lists 13 campsites along it.

## Bridging short unnamed connectors (TM05-98)

Mappers often split a named trail with a short way that has no name: a bridge, a
boardwalk, a road crossing, a junction stub. Same-name assembly (above) stops at such a
way, so the trail opens in pieces. Assembly now bridges the gap, under these rules:

- **Only through unnamed ways.** A gap is never bridged through another named trail.
- **Joined by shared OSM nodes.** Each connector shares an `osm_node_ids` entry with the
  piece before it and the piece after it.
- **Short.** The connectors' combined length is at most `assembly.connector_max_m` in
  `backend/geodata/routes.yml`, which is **300 m**. Setting it to 0 turns bridging off.
- **Same from either side.** The search takes the shortest connector path, with ties
  broken by way id. So whichever piece is clicked, the trail, and its cached profile, is
  the same.

The connectors become part of the assembled trail's geometry, so its line, profile and
campsites run through the gap.

### Measured over every named way outside a route (dev DB, 2026-10-08)

The dev DB has 5,855 named ways outside any route, across both regions.

| | Connector bridging off | On (300 m) |
|---|---|---|
| Assembled trails | 4,043 | 4,017 |
| Names split into more than one assembled trail | 296 | 286 |
| Unnamed connectors used | 0 | 34 |
| Assembled trails that draw as one continuous line | 3,904 | 3,872 |

**Effect on fragmented trails.**
- 25 assembled trails now use connectors, merging 26 previously separate pieces.
- **16 of those 25 now draw as one continuous line.** Examples: S86A, Rim Walk Trail and
  Snowmobile Route S82.
- The other 9 have gaps that are still too long, or not node-connected.

**Why the continuous count falls slightly (3,904 to 3,872).** Some trails that were
continuous on their own are now merged with another piece. The merged trail still has a
gap of its own elsewhere. Count the merged pieces separately and the number of continuous
pieces doesn't fall.

**Most splits are not connector gaps.** Most of the 286 names still split are common names
for unrelated trails far apart ("private", "Multi-Use Trail"), or gaps with no unnamed
way in them.

**Cheney Pond-Irishtown** (`way/1089777523`) is already one continuous 12.8 km way here,
so it needed no bridging. Its only touching way is an unnamed 3.5 km track at its north
end. That is far over the 300 m limit, so it is correctly **not** joined. It shows the
limit doing its job: a long unnamed track is a different route, not a connector.

**Cost.** Assembling all 4,000 trails took 119 s with bridging and 117 s without, so a
single click pays about 0.5 ms more.

## Connecting trails at junctions (TM05-101)

The trail panel's **Connects to** section lists the other named trails that meet this one,
with the mile of each junction on this trail. Clicking one opens it. Hovering one rings
its junctions on the map (`--junction-*` tokens).

**What counts as a junction.**
- **A shared node.** A junction is an **OSM node shared** by one of this trail's ways and
  another **named** way (`Trail.osm_node_ids`). A trail that only crosses or passes close
  by, with no shared node, is not a junction, because OSM puts a node wherever two paths
  really meet.
- **Exact position.** Node ids are stored in vertex order, so a junction's position is
  the vertex at that node.
- **Mile.** The junction is placed along this trail's stitched line, so it matches the
  panel's other miles.

**What gets listed.**
- **Which trail opens.** The other trail is named as the panel would open it: its route
  when its way is a member of one (the longest, as for a clicked way), otherwise the
  assembled trail of its name, opened through its lowest-numbered junction way.
- **Left out:** unnamed ways, ways with this trail's own name (any case), and this route
  itself.
- **Ordering.** A trail that meets this one more than once lists each junction ("mi 1.7
  and 2.3"). Junctions within 50 m along the line are merged into one. Entries are in
  order of their first junction, and capped at 40.

**Measured.** The Van Hoevenberg Trail has 13 connecting trails, from Mr. Van Ski Trail at
mi 0.1 to the Mount Marcy Trail at mi 7.1, computed in 87–149 ms per request. The
routes are looked up in one query, not one per way. Algonquin Trail lists Van Hoevenberg
back.

**Not built yet.** Planning a single hike across several connected trails is a future
story. This section only lists the connections and opens them.
