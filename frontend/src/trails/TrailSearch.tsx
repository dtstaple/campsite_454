/**
 * Trail search and the Discover list (TM05-74): a search box over the map, and under it
 * the named trails in or near the current view, nearest the view centre first. Typing
 * searches every named trail by name (case- and accent-insensitive, server-side); clearing
 * the box goes back to the trails near the view. Picking one opens its trail panel.
 */

import { useEffect, useRef, useState } from "react";
import type * as maplibregl from "maplibre-gl";
import { clampBbox, type Bbox } from "../api";
import { RouteApiError, searchRoutes, type RouteHit } from "./api";
import {
  CAMPSITE_DISTANCE_OPTIONS,
  DIFFICULTY_OPTIONS,
  NO_FILTERS,
  ROUTE_TYPE_OPTIONS,
  activeFilterCount,
  filterParams,
  toggled,
  unknownNote,
  type TrailFilters,
} from "./filters";
import { PHONE_QUERY } from "../components/snaps";
import { emptySearchMessage, routeHitMeta } from "./format";

const VIEW_DEBOUNCE_MS = 400;
const TYPING_DEBOUNCE_MS = 250;
const LIMIT = 25;

type ListState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; hits: RouteHit[]; truncated: boolean; unknown: number }
  | { status: "error"; message: string };

interface Props {
  map: maplibregl.Map | null;
  onPick: (hit: RouteHit) => void;
}

export default function TrailSearch({ map, onPick }: Props) {
  const [query, setQuery] = useState("");
  // TM05-103: on a phone the list starts folded, so the map shows; typing opens it.
  const [open, setOpen] = useState(
    () => typeof window === "undefined" || !window.matchMedia(PHONE_QUERY).matches,
  );
  const [list, setList] = useState<ListState>({ status: "idle" });
  // TM05-85: filters narrow the list; it refreshes as they change, no page reload.
  const [filters, setFilters] = useState<TrailFilters>(NO_FILTERS);
  const [showFilters, setShowFilters] = useState(false);
  const filterKey = JSON.stringify(filterParams(filters));
  // Bumped when the map stops moving, so the list follows the view.
  const [viewVersion, setViewVersion] = useState(0);

  useEffect(() => {
    if (!map) return;
    let timer = 0;
    const onMoveEnd = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setViewVersion((v) => v + 1), VIEW_DEBOUNCE_MS);
    };
    map.on("moveend", onMoveEnd);
    return () => {
      window.clearTimeout(timer);
      map.off("moveend", onMoveEnd);
    };
  }, [map]);

  const requested = useRef(0);
  useEffect(() => {
    if (!map || !open) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const ticket = ++requested.current;
      const centre = map.getCenter();
      setList((previous) => (previous.status === "ready" ? previous : { status: "loading" }));
      searchRoutes(
        {
          q: query.trim() || undefined,
          bbox: clampBbox(map.getBounds().toArray().flat() as Bbox),
          near: [Number(centre.lng.toFixed(5)), Number(centre.lat.toFixed(5))],
          limit: LIMIT,
          filters: JSON.parse(filterKey) as Record<string, string>,
        },
        controller.signal,
      )
        .then((found) => {
          if (ticket === requested.current) {
            setList({
              status: "ready",
              hits: found.results,
              truncated: found.truncated,
              unknown: found.unknown ?? 0,
            });
          }
        })
        .catch((error) => {
          if (controller.signal.aborted) return;
          setList({
            status: "error",
            message: error instanceof RouteApiError ? error.message : String(error),
          });
        });
    }, TYPING_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [map, query, open, viewVersion, filterKey]);

  const heading = query.trim() ? `Trails matching “${query.trim()}”` : "Trails near this view";

  return (
    <section className="trail-search" aria-label="Find a trail">
      <div className="trail-search-bar">
        <input
          type="search"
          className="trail-search-input"
          placeholder="Search trails by name"
          aria-label="Search trails by name"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            // Escape clears the box here instead of closing the panels behind it.
            if (event.key === "Escape" && query) {
              event.stopPropagation();
              setQuery("");
            }
          }}
        />
        <button
          type="button"
          className="trail-search-toggle"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Hide" : "Trails"}
        </button>
      </div>

      {open && (
        <div className="trail-filter-bar">
          <button
            type="button"
            className="trail-search-toggle"
            aria-expanded={showFilters}
            onClick={() => setShowFilters((value) => !value)}
          >
            Filters{activeFilterCount(filters) ? ` (${activeFilterCount(filters)})` : ""}
          </button>
          {activeFilterCount(filters) > 0 && (
            <button type="button" className="trail-search-toggle" onClick={() => setFilters(NO_FILTERS)}>
              Clear filters
            </button>
          )}
        </div>
      )}

      {open && showFilters && <FilterForm filters={filters} onChange={setFilters} />}

      {open && (
        <div className="trail-search-results">
          <div className="trail-search-heading">{heading}</div>
          {list.status === "loading" && <div className="trail-search-note">Loading…</div>}
          {list.status === "error" && <div className="trail-search-note">{list.message}</div>}
          {list.status === "ready" && list.hits.length === 0 && (
            <div className="trail-search-note" role="status">
              {emptySearchMessage(query, activeFilterCount(filters) > 0)}
            </div>
          )}
          {list.status === "ready" && list.hits.length > 0 && (
            <ol className="trail-search-list">
              {list.hits.map((hit) => (
                <li key={hit.osm_id}>
                  <button type="button" className="trail-search-hit" onClick={() => onPick(hit)}>
                    <span className="trail-search-name">{hit.name}</span>
                    <span className="trail-search-meta">{routeHitMeta(hit)}</span>
                  </button>
                </li>
              ))}
            </ol>
          )}
          {list.status === "ready" && unknownNote(list.unknown) && (
            <div className="trail-search-note">{unknownNote(list.unknown)}</div>
          )}
          {list.status === "ready" && list.truncated && (
            <div className="trail-search-note">Showing the nearest {LIMIT}. Search by name for more.</div>
          )}
        </div>
      )}
    </section>
  );
}

/** The filter controls (TM05-85), shared with the Discover page (TM05-102). */
export function FilterForm({
  filters,
  onChange,
}: {
  filters: TrailFilters;
  onChange: (filters: TrailFilters) => void;
}) {
  const set = (patch: Partial<TrailFilters>) => onChange({ ...filters, ...patch });
  return (
    <form className="trail-filters" aria-label="Filter trails" onSubmit={(event) => event.preventDefault()}>
      <fieldset>
        <legend>Length (mi)</legend>
        <input aria-label="Minimum length in miles" inputMode="decimal" placeholder="min"
          value={filters.minLengthMi} onChange={(e) => set({ minLengthMi: e.target.value })} />
        <span aria-hidden="true">–</span>
        <input aria-label="Maximum length in miles" inputMode="decimal" placeholder="max"
          value={filters.maxLengthMi} onChange={(e) => set({ maxLengthMi: e.target.value })} />
      </fieldset>
      <fieldset>
        <legend>Gain (ft)</legend>
        <input aria-label="Minimum gain in feet" inputMode="numeric" placeholder="min"
          value={filters.minGainFt} onChange={(e) => set({ minGainFt: e.target.value })} />
        <span aria-hidden="true">–</span>
        <input aria-label="Maximum gain in feet" inputMode="numeric" placeholder="max"
          value={filters.maxGainFt} onChange={(e) => set({ maxGainFt: e.target.value })} />
      </fieldset>
      <fieldset>
        <legend>Difficulty</legend>
        {DIFFICULTY_OPTIONS.map((option) => (
          <label key={option.value}>
            <input type="checkbox" checked={filters.difficulty.includes(option.value)}
              onChange={() => set({ difficulty: toggled(filters.difficulty, option.value) })} />
            {option.label}
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Type</legend>
        {ROUTE_TYPE_OPTIONS.map((option) => (
          <label key={option.value}>
            <input type="checkbox" checked={filters.routeType.includes(option.value)}
              onChange={() => set({ routeType: toggled(filters.routeType, option.value) })} />
            {option.label}
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Campsites</legend>
        <select aria-label="Has campsites within"
          value={filters.campsitesWithinM ?? ""}
          onChange={(e) => set({ campsitesWithinM: e.target.value ? Number(e.target.value) : null })}>
          <option value="">Any</option>
          {CAMPSITE_DISTANCE_OPTIONS.map((metres) => (
            <option key={metres} value={metres}>
              within {metres < 1000 ? `${metres} m` : `${metres / 1000} km`}
            </option>
          ))}
        </select>
      </fieldset>
    </form>
  );
}
