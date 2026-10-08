/**
 * "Save trail" in the trail panel (TM05-100). Saved trails are listed in the Profile view.
 * Signed out, the button is not shown.
 */

import { useEffect, useState } from "react";
import { savedRowFor, trailRef } from "../plans/draft";
import { listSavedTrails, saveTrail, unsaveTrail, type SavedTrail } from "../plans/savedTrails";
import { useSession } from "../session";
import type { RouteDetail } from "./api";

export default function SaveTrail({ detail }: { detail: RouteDetail }) {
  const { session } = useSession();
  const [saved, setSaved] = useState<SavedTrail[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    listSavedTrails(session)
      .then((rows) => !cancelled && setSaved(rows))
      .catch(() => !cancelled && setSaved([]));
    return () => {
      cancelled = true;
    };
  }, [session]);

  const ref = trailRef(detail);
  if (!session || !ref || saved === null) return null;
  const row = savedRowFor(saved, ref);

  const toggle = async () => {
    setBusy(true);
    setFailed(null);
    try {
      if (row) {
        await unsaveTrail(session, row.id);
        setSaved(saved.filter((entry) => entry.id !== row.id));
      } else {
        const created = await saveTrail(session, ref);
        setSaved([created, ...saved.filter((entry) => entry.id !== created.id)]);
      }
    } catch (error) {
      setFailed((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className={`trail-3d-button trail-save${row ? " is-active" : ""}`}
        aria-pressed={Boolean(row)}
        disabled={busy}
        onClick={() => void toggle()}
      >
        {row ? "Saved" : "Save trail"}
      </button>
      {failed && <span className="trail-gpx-error">{failed}</span>}
    </>
  );
}
