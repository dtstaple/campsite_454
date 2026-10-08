/**
 * The signed-in user's own waypoints (TM05-80): a marker per waypoint on the map, a small
 * panel to add one, and an editor popup to rename, retype, annotate or delete it.
 *
 * Adding: "Add waypoint" arms placement (placement.ts), the next map click drops a draft
 * there, and the editor opens on it. Nothing is saved until Save. Esc cancels either step.
 *
 * Markers are HTML markers rather than a map layer: a person has tens of waypoints, not
 * thousands, and an HTML marker carries the per-kind glyph (kinds.ts) without a sprite
 * sheet, is keyboard-focusable, and needs no change to the shared layer code (layers.ts).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import * as maplibregl from "maplibre-gl";
import type { Session } from "../auth";
import { numericToken } from "../theme";
import { prefersReducedMotion } from "../trails/terrain3d";
import {
  createWaypoint,
  deleteWaypoint,
  listWaypoints,
  updateWaypoint,
  type Waypoint,
} from "./api";
import {
  KINDS,
  NAME_MAX,
  NOTE_MAX,
  defaultName,
  draftError,
  kindStyle,
  type WaypointKind,
} from "./kinds";
import { placement } from "./placement";
import "./waypoints.css";

interface Props {
  map: maplibregl.Map | null;
  session: Session | null;
}

interface Draft {
  /** null for a new waypoint that has not been saved yet. */
  id: number | null;
  name: string;
  kind: WaypointKind;
  note: string;
  lon: number;
  lat: number;
}

const SVG_NS = "http://www.w3.org/2000/svg";

function markerElement(kind: WaypointKind, name: string, draft = false): HTMLButtonElement {
  const style = kindStyle(kind);
  const element = document.createElement("button");
  element.type = "button";
  element.className = `waypoint-marker${draft ? " is-draft" : ""}`;
  element.style.setProperty("--waypoint-color", `var(${style.token})`);
  element.setAttribute("aria-label", `${style.label} waypoint: ${name}`);
  element.title = `${name} (${style.label})`;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", style.glyph);
  path.setAttribute("fill-rule", "evenodd");
  svg.append(path);
  element.append(svg);
  return element;
}

export default function Waypoints({ map, session }: Props) {
  const [waypoints, setWaypoints] = useState<Waypoint[]>([]);
  const [placing, setPlacing] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // --- load ------------------------------------------------------------------------------
  useEffect(() => {
    // Signing in or out remounts this component (Discover keys it by session), so a
    // signed-out page starts empty without clearing state here.
    if (!session) return;
    let cancelled = false;
    listWaypoints(session)
      .then((list) => !cancelled && setWaypoints(list))
      .catch((err: Error) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [session]);

  // --- placement ---------------------------------------------------------------------------
  const waypointsRef = useRef(waypoints);
  useEffect(() => {
    waypointsRef.current = waypoints;
  }, [waypoints]);
  useEffect(() => {
    if (!map || !placing) return;
    placement.active = true;
    const container = map.getContainer();
    container.classList.add("is-placing-waypoint");
    const onClick = (event: maplibregl.MapMouseEvent) => {
      setPlacing(false);
      setConfirmDelete(false);
      setDraft({
        id: null,
        name: defaultName("water", waypointsRef.current),
        kind: "water",
        note: "",
        lon: Number(event.lngLat.lng.toFixed(6)),
        lat: Number(event.lngLat.lat.toFixed(6)),
      });
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPlacing(false);
    };
    map.once("click", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      map.off("click", onClick);
      window.removeEventListener("keydown", onKey);
      container.classList.remove("is-placing-waypoint");
      // Cleared after the click has reached Discover's handler, which runs in the same
      // dispatch and checks the flag.
      window.setTimeout(() => {
        placement.active = false;
      }, 0);
    };
  }, [map, placing]);

  // --- markers -----------------------------------------------------------------------------
  const open = useCallback((waypoint: Waypoint) => {
    setPlacing(false);
    setConfirmDelete(false);
    setError(null);
    setDraft({
      id: waypoint.id,
      name: waypoint.name,
      kind: waypoint.kind,
      note: waypoint.note,
      lon: waypoint.lon,
      lat: waypoint.lat,
    });
  }, []);

  useEffect(() => {
    if (!map) return;
    const markers = waypoints
      .filter((waypoint) => waypoint.id !== draft?.id)
      .map((waypoint) => {
        const element = markerElement(waypoint.kind, waypoint.name);
        element.addEventListener("click", (event) => {
          // Keep the click off the map: no campsite popup or trail panel underneath.
          event.stopPropagation();
          open(waypoint);
        });
        return new maplibregl.Marker({ element, anchor: "center" })
          .setLngLat([waypoint.lon, waypoint.lat])
          .addTo(map);
      });
    return () => markers.forEach((marker) => marker.remove());
  }, [map, waypoints, draft?.id, open]);

  // --- editor popup ------------------------------------------------------------------------
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  const draftKey = draft ? `${draft.id ?? "new"}:${draft.lon}:${draft.lat}` : null;
  const draftKind = draft?.kind;
  const draftRef = useRef(draft);
  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  // The popup lives as long as the draft's identity and position: typing in the form must
  // not rebuild it, or the input would lose focus on every keystroke.
  useEffect(() => {
    const current = draftRef.current;
    if (!map || !draftKey || !current) return;
    const node = document.createElement("div");
    const popup = new maplibregl.Popup({
      closeButton: true,
      closeOnClick: false,
      offset: 18,
      maxWidth: "none",
      className: "waypoint-popup",
    })
      .setLngLat([current.lon, current.lat])
      .setDOMContent(node)
      .addTo(map);
    setSlot(node);
    // The editor opens above the point; bring the point down if the form would be cut
    // off by the top of the map.
    const room = numericToken("--waypoint-editor-room", 340);
    const { y } = map.project([current.lon, current.lat]);
    if (y < room) map.panBy([0, y - room], { duration: prefersReducedMotion() ? 0 : 300 });
    const onClose = () => setDraft(null);
    popup.on("close", onClose);
    return () => {
      popup.off("close", onClose);
      popup.remove();
      setSlot(null);
    };
  }, [map, draftKey]);

  // The draft's marker follows the type chosen in the form.
  useEffect(() => {
    const current = draftRef.current;
    if (!map || !draftKey || !current || !draftKind) return;
    const marker = new maplibregl.Marker({
      element: markerElement(draftKind, current.name, true),
      anchor: "center",
    })
      .setLngLat([current.lon, current.lat])
      .addTo(map);
    return () => {
      marker.remove();
    };
  }, [map, draftKey, draftKind]);

  const save = async () => {
    if (!session || !draft) return;
    const problem = draftError(draft);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    const fields = {
      name: draft.name.trim(),
      kind: draft.kind,
      note: draft.note,
      lon: draft.lon,
      lat: draft.lat,
    };
    try {
      if (draft.id === null) {
        const created = await createWaypoint(session, fields);
        setWaypoints((list) => [...list, created]);
      } else {
        const updated = await updateWaypoint(session, draft.id, fields);
        setWaypoints((list) => list.map((w) => (w.id === updated.id ? updated : w)));
      }
      setDraft(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!session || !draft || draft.id === null) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setBusy(true);
    try {
      await deleteWaypoint(session, draft.id);
      const id = draft.id;
      setWaypoints((list) => list.filter((w) => w.id !== id));
      setDraft(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      setConfirmDelete(false);
    }
  };

  const flyTo = (waypoint: Waypoint) => {
    map?.easeTo({ center: [waypoint.lon, waypoint.lat], zoom: Math.max(map.getZoom(), 14) });
    open(waypoint);
  };

  if (!session) return null;

  return (
    <>
      <section className="panel waypoint-panel" aria-label="My waypoints">
        <div className="waypoint-panel-head">
          <div className="panel-title">My waypoints</div>
          <button
            type="button"
            className={`waypoint-add${placing ? " is-active" : ""}`}
            aria-pressed={placing}
            onClick={() => {
              setDraft(null);
              setPlacing((value) => !value);
            }}
          >
            {placing ? "Cancel" : "+ Add"}
          </button>
        </div>
        {placing && (
          <div className="waypoint-hint" role="status">
            Click the map to place it. Esc cancels.
          </div>
        )}
        {waypoints.length === 0 && !placing ? (
          <div className="waypoint-empty">Mark water, camps and bail-outs for your trips.</div>
        ) : (
          <ul className="waypoint-list">
            {waypoints.map((waypoint) => (
              <li key={waypoint.id}>
                <button type="button" className="waypoint-row" onClick={() => flyTo(waypoint)}>
                  <span
                    className="waypoint-dot"
                    style={{ background: `var(${kindStyle(waypoint.kind).token})` }}
                    aria-hidden="true"
                  />
                  <span className="waypoint-row-name">{waypoint.name}</span>
                  <span className="waypoint-row-kind">{waypoint.kind_label}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {error && !draft && <div className="waypoint-error">{error}</div>}
      </section>

      {slot &&
        draft &&
        createPortal(
          <form
            className="waypoint-editor"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <div className="panel-title">{draft.id === null ? "New waypoint" : "Waypoint"}</div>
            <label className="waypoint-field">
              <span>Name</span>
              <input
                value={draft.name}
                maxLength={NAME_MAX}
                autoFocus
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
            </label>
            <fieldset className="waypoint-kinds">
              <legend>Type</legend>
              {KINDS.map((kind) => (
                <label key={kind.id} className={draft.kind === kind.id ? "is-active" : undefined}>
                  <input
                    type="radio"
                    name="waypoint-kind"
                    value={kind.id}
                    checked={draft.kind === kind.id}
                    onChange={() => {
                      // A default name follows the type until the user types their own.
                      const wasDefault =
                        draft.id === null &&
                        draft.name === defaultName(draft.kind, waypoints);
                      setDraft({
                        ...draft,
                        kind: kind.id,
                        name: wasDefault ? defaultName(kind.id, waypoints) : draft.name,
                      });
                    }}
                  />
                  <span
                    className="waypoint-dot"
                    style={{ background: `var(${kind.token})` }}
                    aria-hidden="true"
                  />
                  {kind.label}
                </label>
              ))}
            </fieldset>
            <label className="waypoint-field">
              <span>Note</span>
              <textarea
                value={draft.note}
                maxLength={NOTE_MAX}
                rows={3}
                placeholder="Optional: flow, access, anything to remember"
                onChange={(event) => setDraft({ ...draft, note: event.target.value })}
              />
            </label>
            <div className="waypoint-coords">
              {draft.lat.toFixed(5)}, {draft.lon.toFixed(5)}
            </div>
            {error && <div className="waypoint-error">{error}</div>}
            <div className="waypoint-actions">
              <button type="submit" className="button-primary" disabled={busy}>
                Save
              </button>
              {draft.id !== null && (
                <button
                  type="button"
                  className={`waypoint-delete${confirmDelete ? " is-confirming" : ""}`}
                  disabled={busy}
                  onClick={() => void remove()}
                >
                  {confirmDelete ? "Really delete?" : "Delete"}
                </button>
              )}
            </div>
          </form>,
          slot,
        )}
    </>
  );
}
