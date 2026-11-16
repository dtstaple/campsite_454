/**
 * Share link for a saved overnight plan (TM05-172): the owner turns on a read-only link,
 * copies it, or stops sharing. Anyone with the link sees the route, nights and days at
 * /shared/<token> without signing in, and nothing about the owner.
 */

import { useEffect, useState } from "react";
import type { Session } from "../auth";
import { getPlan, revokeShare, sharePlan } from "./api";
import { shareUrl } from "./share";

interface Props {
  session: Session;
  planId: number;
}

export default function ShareLink({ session, planId }: Props) {
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    // Keyed by plan in PlanBuilder, so this runs once per plan with fresh state.
    let live = true;
    getPlan(session, planId)
      .then((plan) => live && setToken(plan.share_token ?? null))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [session, planId]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setNote(null);
    try {
      await action();
    } catch (error) {
      setNote((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const url = token ? shareUrl(window.location.origin, token) : null;

  const copy = async () => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setNote("Link copied.");
    } catch {
      setNote("Select the link and copy it.");
    }
  };

  if (!url) {
    return (
      <div className="plan-share">
        <button
          type="button"
          className="trail-3d-button"
          disabled={busy}
          onClick={() => void run(async () => setToken((await sharePlan(session, planId)).token))}
        >
          Share link
        </button>
        {note && <p className="plan-hint" role="status">{note}</p>}
      </div>
    );
  }

  return (
    <div className="plan-share">
      <label className="plan-share-label" htmlFor={`plan-share-${planId}`}>
        Anyone with this link can see this plan, read-only. It doesn't show your name or email.
      </label>
      <div className="plan-share-row">
        <input
          id={`plan-share-${planId}`}
          readOnly
          value={url}
          onFocus={(event) => event.currentTarget.select()}
        />
        <button type="button" className="trail-3d-button" onClick={() => void copy()}>
          Copy
        </button>
      </div>
      <button
        type="button"
        className="plan-link"
        disabled={busy}
        onClick={() =>
          void run(async () => {
            await revokeShare(session, planId);
            setToken(null);
            setNote("Sharing stopped. The old link no longer works.");
          })
        }
      >
        Stop sharing
      </button>
      {note && <p className="plan-hint" role="status">{note}</p>}
    </div>
  );
}
