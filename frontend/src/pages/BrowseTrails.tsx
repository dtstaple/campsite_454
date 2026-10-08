/**
 * Discover trails (TM05-102): browse a region's trails as cards, like AllTrails, apart
 * from the map's small floating search.
 *
 *   region   from pipeline/regions.yml (GET /api/regions/); regions with no data yet are
 *            listed but disabled
 *   filters  the TM05-85 ones (length, gain, difficulty, route type, has campsites)
 *   sort     distance from the last map view, length, gain or name
 *
 * Everything is the TM05-74/85 search endpoint with `region`, `sort`, `offset` and `cards`
 * (docs/api.md). Results come 24 at a time with "Show more". A card opens the map with
 * that trail's panel, and the panel fits the view to it.
 */

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FilterForm } from "../trails/TrailSearch";
import { fetchRegions, searchRoutes, type Region, type RouteHit, type RouteSearch } from "../trails/api";
import { campsitesLine, cardFacts, nearPoint, sparklinePoints } from "../trails/cards";
import { NO_FILTERS, activeFilterCount, filterParams, unknownNote, type TrailFilters } from "../trails/filters";
import { OPEN_STATE_KEY, type OpenRequest } from "../profile/openRequest";
import "../trails/trails.css";
import "../browse/browse.css";

const PAGE = 24;
const REGION_KEY = "campsite.browseRegion";
const LAST_VIEW_KEY = "campsite.lastView";
const SORTS = [
  { id: "distance", label: "Distance from map view" },
  { id: "length", label: "Longest" },
  { id: "gain", label: "Most climbing" },
  { id: "name", label: "Name" },
] as const;
type Sort = (typeof SORTS)[number]["id"];

function remembered(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** The map's last centre, written by the map page as it moves (Discover.tsx). */
function lastMapView(): [number, number] | null {
  const raw = remembered(LAST_VIEW_KEY);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw);
    return Array.isArray(value) && value.length === 2 && value.every(Number.isFinite)
      ? [value[0], value[1]]
      : null;
  } catch {
    return null;
  }
}

type Page = { status: "loading" } | { status: "ready"; search: RouteSearch; hits: RouteHit[] } | { status: "error"; message: string };

export default function BrowseTrails() {
  const navigate = useNavigate();
  const [regions, setRegions] = useState<Region[] | null>(null);
  const [regionId, setRegionId] = useState<string>(() => remembered(REGION_KEY) ?? "adirondacks");
  const [sort, setSort] = useState<Sort>("distance");
  const [filters, setFilters] = useState<TrailFilters>(NO_FILTERS);
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState<Page>({ status: "loading" });
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchRegions(controller.signal)
      .then(setRegions)
      .catch(() => !controller.signal.aborted && setRegions([]));
    return () => controller.abort();
  }, []);

  const region = regions?.find((r) => r.id === regionId) ?? null;
  const params = useMemo(() => filterParams(filters), [filters]);
  const paramsKey = JSON.stringify(params);

  // A new region, sort or filter starts again from the first page.
  const [query, setQuery] = useState({ regionId, sort, paramsKey });
  if (query.regionId !== regionId || query.sort !== sort || query.paramsKey !== paramsKey) {
    setQuery({ regionId, sort, paramsKey });
    setOffset(0);
  }

  useEffect(() => {
    if (!region) return;
    const controller = new AbortController();
    const near = nearPoint(lastMapView(), region.bbox);
    searchRoutes(
      {
        region: region.id,
        sort,
        near,
        limit: PAGE,
        offset,
        cards: true,
        filters: JSON.parse(paramsKey),
      },
      controller.signal,
    )
      .then((search) =>
        setPage((previous) => ({
          status: "ready",
          search,
          hits: offset > 0 && previous.status === "ready" ? [...previous.hits, ...search.results] : search.results,
        })),
      )
      .catch((error: Error) => {
        if (!controller.signal.aborted) setPage({ status: "error", message: error.message });
      });
    return () => controller.abort();
  }, [region, sort, paramsKey, offset]);

  const chooseRegion = (id: string) => {
    setRegionId(id);
    setPage({ status: "loading" });
    try {
      localStorage.setItem(REGION_KEY, id);
    } catch {
      /* not remembered; fine */
    }
  };

  const open = (hit: RouteHit) => {
    const request: OpenRequest = { kind: "trail", trail: { osmId: hit.osm_id }, name: hit.name };
    navigate("/discover", { state: { [OPEN_STATE_KEY]: request } });
  };

  const total = page.status === "ready" ? (page.search.total ?? page.hits.length) : null;
  const unknown = page.status === "ready" ? unknownNote(page.search.unknown ?? 0) : null;

  return (
    <main className="browse">
      <header className="browse-head">
        <h1>Discover trails</h1>
        <p>Browse a region's named trails. Choose one to open it on the map.</p>
      </header>

      <div className="browse-controls">
        <label className="browse-field">
          <span>Region</span>
          <select value={regionId} onChange={(event) => chooseRegion(event.target.value)}>
            {(regions ?? []).map((r) => (
              <option key={r.id} value={r.id} disabled={r.trails === 0}>
                {r.label}
                {r.trails === 0 ? " (no trails yet)" : ` (${r.trails})`}
              </option>
            ))}
          </select>
        </label>
        <label className="browse-field">
          <span>Sort</span>
          <select value={sort} onChange={(event) => setSort(event.target.value as Sort)}>
            {SORTS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className={`trail-3d-button${showFilters || activeFilterCount(filters) ? " is-active" : ""}`}
          aria-expanded={showFilters}
          onClick={() => setShowFilters((value) => !value)}
        >
          Filters{activeFilterCount(filters) ? ` (${activeFilterCount(filters)})` : ""}
        </button>
        {activeFilterCount(filters) > 0 && (
          <button type="button" className="link-button" onClick={() => setFilters(NO_FILTERS)}>
            Clear filters
          </button>
        )}
      </div>
      {showFilters && (
        <div className="browse-filters">
          <FilterForm filters={filters} onChange={setFilters} />
        </div>
      )}

      {page.status === "loading" && <p className="browse-note">Loading trails…</p>}
      {page.status === "error" && <p className="browse-note is-error">{page.message}</p>}
      {page.status === "ready" && (
        <>
          <p className="browse-note">
            {total === 0
              ? activeFilterCount(filters)
                ? "No trails match these filters."
                : "No named trails in this region yet."
              : `${total!.toLocaleString("en-US")} trail${total === 1 ? "" : "s"}`}
            {unknown && <> · {unknown}</>}
          </p>
          <ul className="browse-grid">
            {page.hits.map((hit) => (
              <li key={hit.osm_id}>
                <TrailCard hit={hit} onOpen={() => open(hit)} />
              </li>
            ))}
          </ul>
          {page.search.truncated && (
            <button type="button" className="trail-3d-button browse-more" onClick={() => setOffset(page.hits.length)}>
              Show more
            </button>
          )}
        </>
      )}
    </main>
  );
}

function TrailCard({ hit, onOpen }: { hit: RouteHit; onOpen: () => void }) {
  const points = sparklinePoints(hit.sparkline, 240, 44);
  return (
    <button type="button" className="browse-card" onClick={onOpen}>
      <span className="browse-card-name">{hit.name}</span>
      <span className="browse-card-facts">
        {cardFacts(hit).map((part) => (
          <span key={part}>{part}</span>
        ))}
      </span>
      {points ? (
        <svg className="browse-spark" viewBox="0 0 240 44" preserveAspectRatio="none" aria-label="Elevation profile">
          <polyline points={points} />
        </svg>
      ) : (
        <span className="browse-spark is-empty">No elevation profile yet</span>
      )}
      <span className="browse-card-campsites">{campsitesLine(hit)}</span>
    </button>
  );
}
