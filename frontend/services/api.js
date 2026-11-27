// Every call to the backend goes through here.
import { storage } from "./storage.js";

export const API_BASE = "/api/v1";
const TOKEN_KEY = "tp_token";

let token = storage.get(TOKEN_KEY);
let onSessionExpired = () => {};

export const session = {
  get token() {
    return token;
  },
  setToken(value) {
    token = value;
    storage.set(TOKEN_KEY, value);
  },
  onExpired(handler) {
    onSessionExpired = handler;
  },
};

async function send(path, options, sent) {
  const response = await fetch(API_BASE + path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && sent && !path.startsWith("/auth/")) onSessionExpired();
    throw new Error(data.error || (data.detail ? "The request was not valid." : "HTTP " + response.status));
  }
  return data;
}

const signedIn = (sent, headers = {}) => (sent ? { ...headers, Authorization: "Bearer " + sent } : headers);

export async function api(path, body, method) {
  const sent = token;
  const headers = signedIn(sent);
  if (body) headers["Content-Type"] = "application/json";
  return send(path, {
    method: method || (body ? "POST" : "GET"),
    headers,
    body: body ? JSON.stringify(body) : undefined,
  }, sent);
}

// a file as the whole request body: used for voice recordings
export async function apiUpload(path, blob) {
  const sent = token;
  return send(path, { method: "POST", headers: signedIn(sent, { "Content-Type": blob.type }), body: blob }, sent);
}

export function toolPath(thread, tool, item) {
  return "/trip/" + encodeURIComponent(thread) + "/" + tool + (item ? "/" + encodeURIComponent(item) : "");
}
