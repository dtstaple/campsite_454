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
import { emptySearchMessage, routeHitMeta } from "./format";

const VIEW_DEBOUNCE_MS = 400;
const TYPING_DEBOUNCE_MS = 250;
const LIMIT = 25;

type ListState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; hits: RouteHit[]; truncated: boolean }
  | { status: "error"; message: string };

interface Props {
  map: maplibregl.Map | null;
  onPick: (hit: RouteHit) => void;
}

export default function TrailSearch({ map, onPick }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(true);
  const [list, setList] = useState<ListState>({ status: "idle" });
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
        },
        controller.signal,
      )
        .then((found) => {
          if (ticket === requested.current) {
            setList({ status: "ready", hits: found.results, truncated: found.truncated });
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
  }, [map, query, open, viewVersion]);

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
        <div className="trail-search-results">
          <div className="trail-search-heading">{heading}</div>
          {list.status === "loading" && <div className="trail-search-note">Loading…</div>}
          {list.status === "error" && <div className="trail-search-note">{list.message}</div>}
          {list.status === "ready" && list.hits.length === 0 && (
            <div className="trail-search-note" role="status">
              {emptySearchMessage(query)}
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
          {list.status === "ready" && list.truncated && (
            <div className="trail-search-note">Showing the nearest {LIMIT}. Search by name for more.</div>
          )}
        </div>
      )}
    </section>
  );
}
