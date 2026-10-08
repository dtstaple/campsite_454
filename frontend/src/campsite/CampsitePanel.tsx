/**
 * The campsite panel (TM05-66): everything known about one site, styled like the trail
 * panel. Presentational -- CampsiteDetail owns fetching, the map and saving.
 *
 * Unknown values are never displayed. Each row renders only when its fact exists, so a
 * site with no mapped public land simply has no "Public land" row.
 */

import { useState, type ReactNode } from "react";
import type { CampsiteDetail } from "./api";
import {
  AMENITY_LABELS,
  provenance,
  coordinates,
  distance,
  elevation,
  shelterLabel,
  slope,
  tagValue,
} from "./format";
import SatelliteInset from "./SatelliteInset";
import ScoreBreakdown from "./ScoreBreakdown";
import LegalityVerdict from "./LegalityVerdict";
import Sheet from "../components/Sheet";
import { withoutLegalFactor } from "./legality";

export type CampsiteState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; detail: CampsiteDetail };

/** What the selection knows about the score (TM05-47): a contract-1 breakdown, a total, or neither. */
export interface CampsiteScore {
  breakdown: unknown;
  total: number | null;
}

interface Props {
  state: CampsiteState;
  score: CampsiteScore;
  /** The Save button, built by the page so it shares the map's saved list and session. */
  saveButton: ReactNode;
  onClose: () => void;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="campsite-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export default function CampsitePanel({ state, score, saveButton, onClose }: Props) {
  return (
    <Sheet className="panel trail-panel campsite-panel" label="Campsite">
      <header className="trail-header">
        <div>
          <div className="panel-subtitle trail-eyebrow">Campsite</div>
          {state.status === "ready" ? (
            <Title detail={state.detail} />
          ) : (
            <h2 className="trail-name">{state.status === "loading" ? "Loading…" : "Campsite"}</h2>
          )}
        </div>
        <button type="button" className="trail-close" onClick={onClose} aria-label="Close campsite">
          ×
        </button>
      </header>
      {state.status === "error" && <div className="trail-status is-error">{state.message}</div>}
      {state.status === "ready" && <Body detail={state.detail} score={score} saveButton={saveButton} />}
    </Sheet>
  );
}

function Title({ detail }: { detail: CampsiteDetail }) {
  const name = detail.display_name ?? "Campsite";
  return (
    <>
      <h2
        className={`trail-name${detail.display_name_derived ? " is-derived" : ""}`}
        title={detail.display_name_derived ? "No name in the source data; named from what is nearby" : undefined}
      >
        {name}
      </h2>
      {detail.display_name_derived && <div className="campsite-derived">Unnamed site — name derived from nearby features</div>}
    </>
  );
}

function Body({
  detail,
  score,
  saveButton,
}: {
  detail: CampsiteDetail;
  score: CampsiteScore;
  saveButton: ReactNode;
}) {
  const facts = detail.facts;
  const shelter = shelterLabel(facts?.amenities.shelter_kind ?? null);
  const tags = facts?.amenities.osm_tags ?? {};
  const amenities = Object.entries(AMENITY_LABELS).filter(([key]) => tags[key]);
  const description = tags.description;
  const website = tags.website;

  return (
    <>
      <SatelliteInset lon={detail.lon} lat={detail.lat} />

      <div className="campsite-actions">{saveButton}</div>

      {detail.legality && <LegalityVerdict legality={detail.legality} />}

      <ScoreBreakdown breakdown={withoutLegalFactor(score.breakdown)} total={score.total} />

      <dl className="campsite-facts">
        {shelter && <Row label="Site">{shelter}</Row>}
        {facts?.public_land && (
          <Row label="Public land">
            {facts.public_land.name}
            {facts.public_land.designation && (
              <span className="campsite-sub">{facts.public_land.designation}</span>
            )}
          </Row>
        )}
        {facts?.terrain && (
          <>
            <Row label="Elevation">{elevation(facts.terrain.elevation_m)}</Row>
            <Row label="Slope">{slope(facts.terrain.slope_deg, facts.terrain.slope_pct)}</Row>
          </>
        )}
        {facts?.water && (
          <Row label="Nearest water">
            {facts.water.name}
            <span className="campsite-sub">{distance(facts.water.distance_m)}</span>
          </Row>
        )}
        {facts?.trail && (
          <Row label="Nearest trail">
            {facts.trail.name}
            <span className="campsite-sub">{distance(facts.trail.distance_m)}</span>
          </Row>
        )}
        {amenities.map(([key, label]) => (
          <Row key={key} label={label}>
            {tagValue(tags[key])}
          </Row>
        ))}
        {website && (
          <Row label="Website">
            <a href={website} target="_blank" rel="noopener noreferrer">
              {website.replace(/^https?:\/\//, "")}
            </a>
          </Row>
        )}
        {detail.confidence && (
          <Row label="Data">
            <span className={`campsite-confidence is-${detail.confidence.level}`} title={detail.confidence.reason}>
              {detail.confidence.label}
            </span>
            <span className="campsite-sub">
              {provenance(detail.confidence.source_label, detail.confidence.last_updated)}
            </span>
          </Row>
        )}
        <Row label="Coordinates">
          <CopyCoordinates text={coordinates(detail)} />
        </Row>
      </dl>

      {description && <p className="campsite-description">{description}</p>}
    </>
  );
}

function CopyCoordinates({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text stays selectable */
    }
  }
  return (
    <span className="campsite-coords">
      <code>{text}</code>
      <button type="button" className="campsite-copy" onClick={() => void copy()}>
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}
