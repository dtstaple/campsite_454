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
