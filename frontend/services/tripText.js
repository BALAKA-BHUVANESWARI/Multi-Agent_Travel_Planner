// Building the plain-language requests that are sent back to the planner.
import { capitalise, MONTH_NAMES } from "./format.js";

// the trip as it stands now (after any changes), without a destination
export function requestFor(constraints) {
  const from = constraints.origin_geo?.name || capitalise(constraints.origin);
  const [, month, day] = String(constraints.start_date).split("-").map(Number);
  let text = `Plan a ${constraints.days} day trip from ${from} starting ${day} ${MONTH_NAMES[month - 1]}, ` +
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
