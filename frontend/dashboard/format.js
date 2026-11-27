// How numbers, times and codes are written on the dashboard.
export function ms(value) {
  if (value == null) return "–";
  if (value < 1) return "<1 ms";
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 60000) return `${(value / 1000).toFixed(value < 10000 ? 2 : 1)} s`;
  const seconds = Math.round(value / 1000);
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

export const count = (value) => (value == null ? "–" : Number(value).toLocaleString("en-IN"));

export const percent = (share) => (share == null ? "–" : `${Math.round(share * 1000) / 10}%`);

const stamp = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const when = (iso) => (iso ? stamp.format(new Date(iso)) : "–");

const clock = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const shortDay = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
// short chart labels: the time when everything is from one day, otherwise the date
export function shortLabels(times) {
  const dates = times.map((t) => new Date(t));
  const oneDay = new Set(dates.map((d) => d.toDateString())).size === 1;
  return dates.map((d) => (oneDay ? clock : shortDay).format(d));
}

export const words = (code) => String(code ?? "").replaceAll("_", " ");

export const KINDS = {
  plan: "New plan",
  approve: "Approve / change",
  chat: "Chat message",
  voice: "Voice recording",
  explore: "Destination search",
  photos: "Photo lookup",
  cancel: "Booking cancellation",
};

export const STATUSES = {
  ok: "OK",
  needs_info: "Asked for more info",
  blocked: "Blocked by safety check",
  refused: "Refused",
  rate_limited: "Rate limited",
  failed: "Failed",
};

export const SOURCES = {
  "openstreetmap.places": "OpenStreetMap: places",
  "openstreetmap.nearby": "OpenStreetMap: help nearby",
  "openstreetmap.restaurants": "OpenStreetMap: restaurants",
  "wikivoyage.guide_text": "Wikivoyage: guide text and tips",
  "wikivoyage.sights": "Wikivoyage: sight listings",
  "wikivoyage.restaurants": "Wikivoyage: restaurant listings",
  "wikipedia.nearby_sights": "Wikipedia: sights nearby",
  "wikipedia.photo_articles": "Wikipedia: articles for photos",
  "wikipedia.sight_positions": "Wikipedia: sight positions",
  "open-meteo.forecast": "Open-Meteo: forecast",
  "open-meteo.climate_history": "Open-Meteo: past weather",
  "open-meteo.place_lookup": "Open-Meteo: finding the place",
  built_in_place_list: "Built-in place list",
  local_text_search: "Local tips search",
  "live_prices.page": "Live prices: page read",
  "live_prices.exchange_rate": "Live prices: exchange rate",
  "live_prices.flights": "Live flight prices → estimate",
  "live_prices.hotels": "Live hotel prices → estimate",
  "weather.offline_estimate": "Weather → offline estimate",
};
export const sourceName = (key) => SOURCES[key] || key;

export const PLAN_SOURCES = {
  wikipedia: "Wikipedia",
  wikivoyage: "Wikivoyage",
  openstreetmap: "OpenStreetMap",
  built_in: "Built-in list",
  generic: "Generic filler (no real place)",
};

export const STEP_TYPES = {
  agent: "Agent",
  tool: "Tool call",
  retrieval: "Data lookup",
  retrieval_wait: "Data lookup",
  llm: "AI request",
  llm_call: "AI call",
  voice: "Voice",
  guardrail: "Safety check",
  fact_check: "Made-up fact check",
  log: "Agent note",
  request: "Request",
};

const said = (v) => (typeof v === "boolean" ? (v ? "yes" : "no") : /^[a-z]+(_[a-z]+)+$/.test(v) ? words(v) : String(v));

export const facts = (attrs) =>
  Object.entries(attrs || {})
    .filter(([, v]) => v !== "" && v != null && !(typeof v === "object" && !Object.keys(v).length))
    .map(([k, v]) => [words(k), typeof v === "object" ? Object.entries(v).map(([a, b]) => `${words(a)}: ${b}`).join(", ") : said(v)]);
