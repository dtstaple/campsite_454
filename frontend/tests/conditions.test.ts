import { test } from "node:test";
import assert from "node:assert/strict";
import {
  alertTone,
  alertUntil,
  dayLabel,
  fetchedText,
  precipitationText,
  sourceText,
  temperatureText,
  trailPoint,
  windText,
  type AlertsSection,
  type ForecastDay,
  type ForecastSection,
  type WeatherAlert,
} from "../src/conditions/conditions.ts";

const DAY: ForecastDay = {
  date: "2026-10-29",
  temperature_min_c: 3.3,
  temperature_max_c: 12.2,
  precipitation_mm: 3.1,
  precipitation_probability_pct: 40,
  wind_max_kmh: 14.5,
  gust_max_kmh: 33.8,
};

const ALERT: WeatherAlert = {
  id: "urn:oid:1",
  event: "Frost Advisory",
  headline: "Frost Advisory until 9 AM",
  severity: "Minor",
  urgency: "Expected",
  certainty: "Likely",
  effective: "2026-10-27T15:02:00-04:00",
  onset: "2026-10-28T01:00:00-04:00",
  expires: "2026-10-28T09:00:00-04:00",
  ends: null,
  sender_name: "NWS Albany NY",
  area: "Hamilton",
  description: "Frost likely.",
  instruction: null,
};

const NOW = new Date("2026-10-28T12:30:00Z");

test("a forecast day reads in °F, inches and mph", () => {
  assert.equal(temperatureText(DAY), "54° / 38°F");
  assert.equal(precipitationText(DAY), "40% rain, 0.12 in");
  assert.equal(windText(DAY), "Wind 9 mph, gusts 21");
});

test("a dry day and missing values degrade to short text, never NaN", () => {
  const dry = { ...DAY, precipitation_mm: 0, precipitation_probability_pct: 0 };
  assert.equal(precipitationText(dry), "Dry");
  assert.equal(precipitationText({ ...dry, precipitation_probability_pct: 10 }), "Dry (10% chance)");
  assert.equal(temperatureText({ ...DAY, temperature_min_c: null }), "high 54°F");
  assert.equal(temperatureText({ ...DAY, temperature_min_c: null, temperature_max_c: null }), "—");
  assert.equal(windText({ ...DAY, wind_max_kmh: null }), null);
  assert.equal(windText({ ...DAY, gust_max_kmh: null }), "Wind 9 mph");
});

test("days are labelled Today, Tomorrow, then by weekday", () => {
  assert.deepEqual(
    ["2026-10-29", "2026-10-30", "2026-10-31"].map(dayLabel),
    ["Today", "Tomorrow", "Sat"],
  );
});

test("Extreme and Severe alerts are highlighted most; everything else less", () => {
  assert.equal(alertTone("Extreme"), "severe");
  assert.equal(alertTone("Severe"), "severe");
  assert.equal(alertTone("Moderate"), "moderate");
  assert.equal(alertTone("Unknown"), "moderate");
});

test("an alert says until when, from its end or else its expiry", () => {
  assert.match(alertUntil(ALERT) ?? "", /^until \w{3} \d{1,2}:\d{2} (AM|PM)$/);
  assert.equal(alertUntil({ ...ALERT, ends: null, expires: null }), null);
  assert.equal(alertUntil({ ...ALERT, ends: "not a date" }), null);
});

test("the fetch time reads relative, then as a clock time past an hour", () => {
  assert.equal(fetchedText("2026-10-28T12:29:40Z", NOW), "fetched just now");
  assert.equal(fetchedText("2026-10-28T12:18:00Z", NOW), "fetched 12 min ago");
  assert.match(fetchedText("2026-10-28T10:00:00Z", NOW), /^fetched \d{1,2}:\d{2} (AM|PM)$/);
});

test("each section names its source, with the fetch time once it has one", () => {
  const ok: ForecastSection = {
    source: "Open-Meteo",
    source_url: "https://api.open-meteo.com/v1/forecast",
    status: "ok",
    fetched_at: "2026-10-28T12:26:00Z",
    expires_at: "2026-10-28T13:26:00Z",
    cached: true,
    timezone: "America/New_York",
    days: [DAY],
  };
  const failed: AlertsSection = {
    source: "US National Weather Service",
    source_url: "https://api.weather.gov/alerts/active",
    status: "error",
    message: "Weather alerts unavailable right now.",
  };
  assert.equal(sourceText(ok, NOW), "Open-Meteo · fetched 4 min ago");
  assert.equal(sourceText(failed, NOW), "US National Weather Service");
});

test("a trail's conditions are for the middle vertex of its line", () => {
  assert.deepEqual(
    trailPoint([
      [-74.0, 44.1],
      [-73.95, 44.15],
      [-73.9, 44.2],
    ]),
    { lat: 44.15, lon: -73.95 },
  );
  assert.equal(trailPoint([]), null);
});
