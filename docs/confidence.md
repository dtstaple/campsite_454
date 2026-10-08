# Campsite confidence and provenance (TM05-77)

Every campsite record says how far to trust it, where it came from, and when we last
fetched it. This is a statement about the **record**, not the site. A well-used spot can be
`limited_info` simply because nobody has tagged it.

Code: `backend/geodata/confidence.py`. Served as `confidence` on
`GET /api/campsites/<id>/detail/` (docs/api.md). Shown as the **Data** row in the
campsite panel.

## The levels

| Level | Label | Rule |
|---|---|---|
| `official` | Official listing | The record comes from an official dataset. Today that is **only Recreation.gov (RIDB)**, the federal reservation system. |
| `community_mapped` | Community-mapped | An OpenStreetMap record with a **name**, or with at least **2 informative tags**. |
| `limited_info` | Limited info | An OpenStreetMap record with **no name and fewer than 2 informative tags**: somebody marked a spot, and little more is known. |

Checked in that order. A record from a source with no rule yet is `limited_info`.

**Informative tags** are the OSM tags the panel surfaces (`operator`, `description`, `tents`,
`fireplace`, `toilets`, `drinking_water`, `fee`, `access`, and the rest of
`enrichment.facts.OSM_TAGS`) plus the ones the adapter reads into Campsite fields
(`shelter_type`, `group_only`, `backcountry`, `reservation`, `capacity`).
`tourism`, `amenity` and `name` do not count: every record has the first two, and the
name is checked on its own. Blank values do not count.

The threshold is `MIN_INFORMATIVE_TAGS` in `confidence.py`.

### Why an NYSDEC operator tag is not "official"

136 Adirondack OSM records carry `operator=NYSDEC` (or similar). That is a contributor
saying who runs the site, not the agency publishing its own list, so these records are
`community_mapped`. The operator is reported separately (`confidence.operator`, and the
panel's existing **Operator** row), so a user still sees it.

If NYSDEC's own campsite data is ever ingested, it becomes a second `official` source.

## Provenance

- **`source` / `source_label`:** the dataset the record came from, for example
  `osm` / "OpenStreetMap".
- **`last_updated`:** when the **ingest run** that last created or updated the record
  finished (`IngestRun.finished_at`, through the record's `last_run`). It is when we last
  confirmed the record, not when the source last edited it: the OSM query does not ask for
  element timestamps. A record with no run falls back to the row's own `updated_at`.

## Measured (dev database, 2026-10-07)

| Level | Records |
|---|---|
| `official` (RIDB, White Mountains) | 660 |
| `community_mapped` (OSM) | 569 |
| `limited_info` (OSM) | 271 |
| **Total** | **1,500** |
