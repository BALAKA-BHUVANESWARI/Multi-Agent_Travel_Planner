// Plain words for the codes on the Guardrails and Hallucination checks tabs.
import { words } from "./format.js";

export const named = (names, code) => names?.[code] || words(code);

export const INPUT_REASONS = {
  prompt_injection: "Tried to change the AI’s instructions",
  sensitive_data: "Contained a card number, ID number, code or password",
  off_topic: "Not about travel",
  too_long: "Too long",
  empty: "Empty",
};

export const AI_CHECKS = {
  wrong_format: ["Answer not in the asked format", "The next try or backup model is used, or the built-in rules"],
  ranking_ids: ["Activity ids that were not on the list", "Those ids are ignored"],
  summary_amounts: ["Summary with a rupee amount not in the plan", "The AI summary is left out; the standard one is shown"],
  summary_facts: ["Summary with a place, date, amount or hotel feature not in the plan", "The AI summary is left out; the standard one is shown"],
  chat_facts: ["Chat answer with a place, date, amount or hotel feature not in the plan", "The AI answer is left out; a standard reply is shown"],
  filled_value: ["A starting city, budget or trip length you did not state", "The planner asks you for it"],
  invented_destination: ["A destination you did not name, when you asked for ideas", "Suggestions are offered instead"],
};

export const RULES = {
  input_check: "Input check",
  feedback_check: "Input check (change request)",
  sensitive_data_withheld: "Private detail withheld",
  spoken_sensitive_data: "Private detail in a recording",
  untrusted_text_cleaned: "Web text cleaned",
  ai_wrong_format: "AI answer format",
  ai_ranking_ids: "AI activity ranking",
  writer_amounts: "AI summary amounts",
  writer_facts: "AI summary details",
  chat_facts: "AI chat details",
  ai_filled_value: "AI trip details",
  ai_invented_destination: "AI destination",
  critic_checks: "Plan checks",
  revision_limit: "Change limit",
  change_not_possible: "Change not possible",
  feedback_understood: "Change not understood",
  rate_limit: "Rate limit",
  chat_fixed_reply: "Fixed chat reply",
  place_check: "“Did you mean …?”",
};

export const PLAN_CODES = {
  bad_date: "A date could not be read",
  date_in_past: "A date is in the past",
  bad_duration: "Number of days not allowed",
  day_count: "Wrong number of days in the plan",
  date_sequence: "Days are not in order",
  hotel_nights: "Hotel nights do not match the trip",
  no_itinerary: "No day plan",
  overlap: "Two items overlap",
  too_many_items: "Too many items in a day",
  before_arrival: "Something planned before arrival",
  after_departure: "Something planned after departure",
  rain_outdoor: "Outdoor item on a rainy day",
  no_budget: "No budget total",
  price_untraceable: "A price that no tool returned",
  total_mismatch: "Totals do not add up",
  partial_plan: "Part of the plan is missing",
};

export const RATE_BUCKETS = {
  plan: "Too many new plans in a short time",
  act: "Too many actions in a short time",
  read: "Too many page requests in a short time",
  voice: "Too many voice recordings in a short time",
  voice_daily: "Today’s voice limit used up",
  auth: "Too many sign-in tries",
};

export const CHAT_TOPICS = {
  visa: "Visa or entry rules",
  emergency: "Emergency",
  booking: "Asked to book, approve or cancel",
};

export const CHANGE_KINDS = {
  days: "number of days",
  travelers: "number of travellers",
  month_day: "start date",
  destination: "destination",
  travel_mode: "way of travelling",
};

export const JOBS = {
  summary: ["AI trip summary", "Rupee amounts, dates, day counts and place names, against the plan"],
  chat: ["AI chat answer", "Amounts, dates, day counts and place names, against the plan (places in your question are allowed)"],
  request_reading: ["Values the AI read from a request", "Places, days, budget and interests the rules could not read, against your typed words"],
  ranking: ["AI activity ranking", "Activity ids that were not on the list it was given"],
};

export const FLAG_KINDS = {
  amounts: "Money amount",
  dates: "Date",
  day_counts: "Day or night count",
  places: "Place name",
  days: "Number of days",
  budget: "Budget",
  preferences: "Interest",
  unknown_ids: "Activity id",
};

export const VERDICTS = { real: "Real problem", false_alarm: "False alarm" };
