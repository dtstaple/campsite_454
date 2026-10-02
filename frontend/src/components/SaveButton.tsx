/**
 * Save / unsave for a campsite, rendered by Discover into the open popup's actions slot
 * through a portal.
 *
 * Being a React component is the point: it re-renders from the page's `saved` list, so
 * it can never show a stale state, and it needs no refs or hand-attached listeners.
 */

import { useState } from "react";

interface Props {
  isSaved: boolean;
  onToggle: () => Promise<void>;
}

export default function SaveButton({ isSaved, onToggle }: Props) {
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    setBusy(true);
    try {
      await onToggle();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      className={`popup-save${isSaved ? " is-saved" : ""}`}
      aria-pressed={isSaved}
      disabled={busy}
      onClick={() => void handleClick()}
    >
      {isSaved ? "Saved ✓" : "Save"}
    </button>
  );
}
