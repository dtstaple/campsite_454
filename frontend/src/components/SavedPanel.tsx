/**
 * The signed-in user's saved campsites, as a compact floating panel.
 *
 * Extracted from Discover.tsx unchanged in behaviour: a row flies the map to the site,
 * the × unsaves it.
 */

import type { SavedCampsite } from "../saved";

interface Props {
  saved: SavedCampsite[];
  onShow: (campsite: SavedCampsite) => void;
  onUnsave: (campsite: SavedCampsite) => void;
}

export default function SavedPanel({ saved, onShow, onUnsave }: Props) {
  return (
    <section className="panel saved-panel" aria-label="Saved campsites">
      <div className="panel-title">Saved</div>
      {saved.length === 0 ? (
        <div className="saved-empty">Nothing saved yet. Open a campsite and choose Save.</div>
      ) : (
        <ul className="saved-list">
          {saved.map((campsite) => (
            <li key={campsite.id}>
              <button
                type="button"
                className="saved-row"
                onClick={() => onShow(campsite)}
                title="Show on the map"
              >
                {campsite.name}
              </button>
              <button
                type="button"
                className="saved-remove"
                onClick={() => onUnsave(campsite)}
                aria-label={`Unsave ${campsite.name}`}
                title="Unsave"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
