# Class diagram: the current data model (TM05-150)

This is every Django model CampSite stores, with its key fields and relationships. It was
read from the code on 2026-11-03: `backend/*/models.py`, after TM05-149.

- **Source.** The Mermaid block below is the source. GitHub renders it in place.
- **Image.** [`class-diagram.svg`](class-diagram.svg) is the same diagram, rendered with
  mermaid-cli (see [Re-rendering](#re-rendering)).
- **Visual Paradigm.** The course's version is redrawn from this one and attached to
  TM05-150 in Jira.

**How to read it.**

- **Fields.** Each class lists its key fields, not every column. The rest are in the model
  files named in the [table](#models-by-app).
- **Geometry.** `geom` is always EPSG:4326. `geom_m` is the same geometry in EPSG:5070
  metres, a column PostGIS generates (`geodata.models.metric_geom`).
- **Solid lines** are database foreign keys, with their cardinality and the
  `related_name`.
- **Dotted lines** are references by a stable source id, not by row: `osm_id`,
  `from_way`, `planned_route` and `*_source_id`.
  - These survive a re-ingest, which replaces rows.
  - The database does not enforce them.
- **`<<abstract>>`** `SourceRecord` has no table. Its seven subclasses each get its fields.
- **User** is Django's `auth.User` (`settings.AUTH_USER_MODEL`).
- **Deleting a user cascades** to everything they own (`tests/test_accounts_delete.py`).

```mermaid
classDiagram
    direction LR

    %% ---------------- ingested reference data (geodata) ----------------
    class SourceRecord {
        <<abstract>>
        +str source  "ridb | osm | nhd | padus"
        +str source_id  "upsert key, unique with source"
        +str name
        +json raw
        +datetime created_at
        +datetime updated_at
    }
    class IngestRun {
        +str source
        +str region
        +datetime started_at
        +datetime finished_at
        +int record_count
        +str status  "success | partial | failed"
        +json parameters
    }
    class Campsite {
        +Point geom
        +Point geom_m
        +str site_type  "designated | primitive | lean_to | group | unknown"
        +bool reservable
        +int capacity
    }
    class Trail {
        +MultiLineString geom
        +MultiLineString geom_m
        +str trail_type
        +float length_m
        +json osm_node_ids
    }
    class TrailRoute {
        +int osm_id  "OSM relation id"
        +str ref
        +str network
        +str operator
        +json member_way_ids
        +MultiLineString geom
        +float length_m
    }
    class Landmark {
        +Point geom
        +str kind  "peak | trailhead"
        +float elevation_m
    }
    class Connector {
        +MultiLineString geom
        +str highway
        +float length_m
        +json osm_node_ids
    }
    class WaterFeature {
        +Geometry geom  "line or polygon"
        +str feature_type  "stream | lake | wetland | spring | other"
        +bool perennial
    }
    class PublicLand {
        +MultiPolygon geom
        +str manager
        +str designation
        +str public_access  "open | restricted | closed | unknown"
        +str gap_status  "PAD-US GAP 1-4"
    }

    SourceRecord <|-- Campsite
    SourceRecord <|-- Trail
    SourceRecord <|-- TrailRoute
    SourceRecord <|-- Landmark
    SourceRecord <|-- Connector
    SourceRecord <|-- WaterFeature
    SourceRecord <|-- PublicLand
    SourceRecord "0..*" --> "0..1" IngestRun : last_run (SET_NULL)
    TrailRoute ..> Trail : member_way_ids = way ids

    %% ---------------- derived facts (enrichment) ----------------
    class CampsiteFacts {
        +str method_version
        +datetime computed_at
        +str land_name, land_access, land_gap_status
        +float water_distance_m
        +bool water_perennial
        +float trail_distance_m
        +float elevation_m
        +float slope_deg
        +str display_name
        +json factor_results
        +str factor_digest
    }
    class RouteFacts {
        +float length_m
        +float gain_m
        +float loss_m
        +str difficulty
        +str route_type
        +float nearest_campsite_m
    }
    Campsite "1" -- "0..1" CampsiteFacts : facts
    TrailRoute "1" -- "0..1" RouteFacts : facts
    CampsiteFacts ..> PublicLand : land_source_id
    CampsiteFacts ..> WaterFeature : water_source_id
    CampsiteFacts ..> Trail : trail_source_id (way or route)

    %% ---------------- terrain pipeline (terrain) ----------------
    class TerrainRun {
        +str region
        +datetime started_at
        +datetime finished_at
        +str config_digest
        +str dem_digest
        +json tool_versions
        +json dem_source
        +json timings
        +json counts
    }
    class TerrainFacts {
        +json values  "twi, slope_deg, aspect_deg, dev, ..."
        +str pooling, cold_air  "low | medium | high"
        +str facing, sun
        +str shelter, wind  "sheltered | moderate | exposed"
        +float wind_from_deg
        +float view_area_km2
        +bool water_view
        +MultiPolygon viewshed
    }
    class TerrainZone {
        +str region
        +str layer  "pooling-risk | exposure | ..."
        +str zone_class
        +str tile  "blank once merged"
        +float area_m2
        +MultiPolygon geom
    }
    class TerrainTile {
        +str region
        +str tool
        +str tile
        +str config_digest
        +str dem_digest
        +float seconds
    }
    Campsite "1" -- "0..1" TerrainFacts : terrain
    TerrainRun "0..1" <-- "0..*" TerrainFacts : run (SET_NULL)
    TerrainRun "0..1" <-- "0..*" TerrainZone : run (SET_NULL)
    TerrainRun "0..1" <-- "0..*" TerrainTile : run (SET_NULL)

    %% ---------------- routing graph (routing) ----------------
    class TrailGraphBuild {
        +str region
        +datetime started_at
        +int ways, nodes, edges
        +int elevation_samples
        +json provenance  "elevation_source, timings"
    }
    class TrailEdge {
        +str region
        +str kind  "trail | track | road | bridge"
        +int start_node, end_node  "OSM node ids"
        +float start_along_m
        +float length_m
        +float ascent_m, descent_m
        +float cost_factor
        +json samples
        +LineString geom
    }
    TrailGraphBuild "1" *-- "0..*" TrailEdge : trail_edges
    TrailEdge "0..*" --> "0..1" Trail : trail
    TrailEdge "0..*" --> "0..1" Connector : connector

    %% ---------------- the user's own data (accounts, planning) ----------------
    class User {
        <<django.contrib.auth>>
        +str username
        +str email
        +str password  "hashed"
        +datetime date_joined
    }
    class SavedCampsite {
        +datetime created_at
    }
    class SavedTrail {
        +int osm_id
        +str from_way
        +str name
        +float length_m
    }
    class ScoringWeights {
        +json weights  "factor -> weight"
        +datetime updated_at
    }
    class Waypoint {
        +str name
        +str kind  "water | camp | bailout | custom"
        +str note
        +Point geom
    }
    class Plan {
        <<TripPlan>>
        +str name
        +int osm_id
        +str from_way
        +str planned_route  "routing id"
        +str trail_name
    }
    class PlanStop {
        +str candidate_id  "potential site, no row"
        +Point point
    }
    class Hike {
        +str name
        +str mode  "trail | free"
        +bool simulated
        +int osm_id
        +str from_way
        +datetime started_at, ended_at
        +float distance_m, gain_m, moving_s
        +json track  "segments of lon, lat, ele, t"
        +MultiLineString geom
    }

    User "1" *-- "0..*" SavedCampsite : saved_campsites
    SavedCampsite "0..*" --> "1" Campsite : campsite (saved_by)
    User "1" *-- "0..*" SavedTrail : saved_trails
    User "1" *-- "0..1" ScoringWeights : scoring_weights
    User "1" *-- "0..*" Waypoint : waypoints
    User "1" *-- "0..*" Plan : trip_plans
    Plan "1" *-- "0..*" PlanStop : stops
    PlanStop "0..*" --> "0..1" Campsite : campsite (plan_stops)
    User "1" *-- "0..*" Hike : hikes
    SavedTrail ..> TrailRoute : osm_id
    SavedTrail ..> Trail : from_way
    Plan ..> TrailRoute : osm_id
    Plan ..> Trail : from_way
    Plan ..> TrailEdge : planned_route (solved on the graph)
    Hike ..> TrailRoute : osm_id
    Hike ..> Trail : from_way
```

## Models by app

The diagram shows two models under shorter names. `Plan` is `planning.TripPlan`, whose
nights are `planning.PlanStop`. `User` is `django.contrib.auth.models.User`.

| App | Model | What it is | File |
|---|---|---|---|
| geodata | `SourceRecord` (abstract) | Shared fields and the `(source, source_id)` upsert key of every ingested row | `backend/geodata/models.py` |
| geodata | `Campsite` | A campsite: a point (RIDB, OSM) | 〃 |
| geodata | `Trail` | One OSM way, with its ordered node ids | 〃 |
| geodata | `TrailRoute` | A named hiking route: an OSM `route=hiking` relation over ways | 〃 |
| geodata | `Landmark` | A peak or a trailhead | 〃 |
| geodata | `Connector` | A road or sidewalk the routing graph may walk between trails | 〃 |
| geodata | `WaterFeature` | NHD flowlines and waterbodies | 〃 |
| geodata | `PublicLand` | PAD-US land units: manager, access, GAP status | 〃 |
| geodata | `IngestRun` | Provenance of one adapter run | 〃 |
| enrichment | `CampsiteFacts` | Derived per-site facts: land, water, trail, slope, stored factor results | `backend/enrichment/models.py` |
| enrichment | `RouteFacts` | Derived per-route facts for the Discover filters | 〃 |
| terrain | `TerrainRun` | Provenance of one `make terrain` | `backend/terrain/models.py` |
| terrain | `TerrainFacts` | Per-site terrain: pooling, facing, shelter, cold air, wind, viewshed | 〃 |
| terrain | `TerrainZone` | Classified polygons (pooling risk, exposure) | 〃 |
| terrain | `TerrainTile` | One finished tile of one tool, for resuming | 〃 |
| routing | `TrailGraphBuild` | One routing graph build: counts, provenance, timings | `backend/routing/models.py` |
| routing | `TrailEdge` | One graph edge: a stretch of a way between junctions, with its climb | 〃 |
| accounts | `SavedCampsite` | A user's bookmarked campsite | `backend/accounts/models.py` |
| accounts | `ScoringWeights` | A user's own factor weights | 〃 |
| planning | `Waypoint` | A point the user marked | `backend/planning/models.py` |
| planning | `TripPlan` ("Plan") | An overnight plan along one trail or planned route | 〃 |
| planning | `PlanStop` | One night of a plan: a campsite or a potential site | 〃 |
| planning | `SavedTrail` | A trail the user saved | 〃 |
| planning | `Hike` | A recorded hike: its track and numbers | 〃 |
| analysis | `AnalysisResult` | The on-demand analysis cache (weather, 3DEP answers), keyed by a hash | `backend/analysis/models.py` |

**Not drawn.** `AnalysisResult` has no relationships: its rows are keyed by a hash of
(analysis, version, geometry, window, params), so it is left out of the diagram. The
`health` app has no models.

## Models from the old diagram that are gone

The original project diagram, from the proposal, had three models that CampSite does not
have: `Booking`, `Payment` and `Outfitter`.

- **No code for them exists.** Nothing in `backend/`, the migrations or the git history
  defines or mentions them (checked with `git log --all -S` on 2026-11-03), so there was
  nothing to delete.
- **They left with the scope.** CampSite finds and scores backcountry sites (CLAUDE.md,
  "The project"). Reservations stay with the source: `Campsite.reservable` records
  whether RIDB says a site can be booked, and the app links out rather than taking
  bookings or payments. No outfitter listings were ever ingested.
- **What took their place.** The user-side classes are now the saved items
  (`SavedCampsite`, `SavedTrail`, `ScoringWeights`) and the planning models
  (`Waypoint`, `TripPlan`/`PlanStop`, `Hike`).

## Re-rendering

When a model changes, update the Mermaid block above, then regenerate the image:

```
npx -y @mermaid-js/mermaid-cli@11.4.2 -i docs/class-diagram.md -o docs/class-diagram.svg
```

mermaid-cli renders each Mermaid block in a Markdown file. For a single block, the output
is `class-diagram-1.svg`; rename it to `class-diagram.svg`.
