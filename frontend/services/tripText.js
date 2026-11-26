// Building the plain-language requests that are sent back to the planner.
import { capitalise, MONTH_NAMES } from "./format.js";

// the trip as it stands now (after any changes), without a destination
export function requestFor(constraints) {
  const from = constraints.origin_geo?.name || capitalise(constraints.origin);
  const [, month, day] = String(constraints.start_date).split("-").map(Number);
  let text = `Plan a ${constraints.days} day trip from ${from}, starting ${day} ${MONTH_NAMES[month - 1]}, ` +
    `budget ${constraints.budget} for ${constraints.travelers} people`;
  if (constraints.preferences?.length) {
    text += ", love " + constraints.preferences.map((p) => (p === "family" ? "family-friendly" : p)).join(" and ");
  }
  if (constraints.pace === "relaxed") text += ", relaxed pace";
  return text;
}

export const withDestination = (request, name) =>
  request.replace(/\s*\|\s*(destination|travel):[^|]*/gi, "") + " | destination: " + name;

export const withTravelMode = (request, mode) =>
  request.replace(/\s*\|\s*travel:.*$/i, "") + (mode === "any" ? " | travel: any mode" : " | travel: by " + mode);

// rows of the "planning for a group" form -> what the API expects; empty rows are left out
export const readGroup = (rows) => {
  const list = (text) => text.split(",").filter((x) => x.trim());
  return rows
    .map((row) => ({ name: row.name.trim(), likes: list(row.likes), avoid: list(row.avoid) }))
    .filter((m) => m.name || m.likes.length || m.avoid.length);
};

const cleanPlace = (name) => name.replace(/[|,;]/g, " ").replace(/\s+/g, " ").trim();

const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// The sentence carries a day and month, not a year, so the date picker allows tomorrow up to eleven months ahead.
export function dateLimits(today) {
  return {
    min: isoDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1)),
    max: isoDay(new Date(today.getFullYear() + 1, today.getMonth(), 0)),
  };
}

export function checkTripForm(form, limits) {
  if (!cleanPlace(form.from)) return "Tell me which city or town you are travelling from.";
  if (!/^\s*₹?\s*\d[\d,]*(\.\d+)?\s*(k|l|lakhs?)?\s*$/i.test(form.budget)) {
    return "Enter your total budget, for example 60000 or 1.5 lakh.";
  }
  if (form.date && (form.date < limits.min || form.date > limits.max)) {
    return `Choose a start date from ${limits.min} to ${limits.max}.`;
  }
  return "";
}

// The destination goes in the "| destination:" marker, which the planner reads exactly as written.
export function requestFromForm(form) {
  const to = cleanPlace(form.to);
  let text = `${to ? "Plan" : "Suggest"} a ${form.days} day trip from ${cleanPlace(form.from)}`;
  if (form.date) {
    const [, month, day] = form.date.split("-").map(Number);
    text += `, starting ${day} ${MONTH_NAMES[month - 1]}`;
  }
  text += `, budget ${form.budget.replace("₹", "").trim()} for ${form.travellers} people`;
  if (form.interests.length) {
    text += ", love " + form.interests.map((p) => (p === "family" ? "family-friendly" : p)).join(" and ");
  }
  return to ? `${text} | destination: ${to}` : text;
}
