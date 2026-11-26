// Turning values into text.
export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];

export const capitalise = (text) => String(text ?? "").replace(/\b\w/g, (c) => c.toUpperCase());

export const inr = (amount) => "₹" + Math.round(amount).toLocaleString("en-IN");

export const signedInr = (amount) => (amount > 0 ? "+" : amount < 0 ? "−" : "") + inr(Math.abs(amount));

export function shortDay(iso) {
  const [, month, day] = String(iso).split("-").map(Number);
  return `${day} ${MONTH_NAMES[month - 1].slice(0, 3)}`;
}

export const longDay = (iso) => `${shortDay(iso)} ${String(iso).slice(0, 4)}`;

export const placeName = (constraints, role) =>
  constraints[role + "_geo"]?.name || capitalise(constraints[role]);

// Only https links are ever followed: anything else (javascript:, data:) becomes "#".
export const safeUrl = (url) => (/^https:\/\//.test(String(url)) ? String(url) : "#");

export const phoneNumbers = (value) => String(value).split(/\s+or\s+|,\s*/).filter(Boolean);

export const phoneHref = (number) => "tel:" + number.replace(/[^0-9+]/g, "");

// React escapes text by itself. This is only for Leaflet's tooltips and popups, which read strings as HTML.
export const escapeHtml = (text) =>
  String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
