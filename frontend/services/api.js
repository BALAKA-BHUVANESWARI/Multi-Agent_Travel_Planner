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

export async function api(path, body, method) {
  const headers = {};
  const sent = token;
  if (sent) headers.Authorization = "Bearer " + sent;
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(API_BASE + path, {
    method: method || (body ? "POST" : "GET"),
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && sent && !path.startsWith("/auth/")) onSessionExpired();
    throw new Error(data.error || (data.detail ? "The request was not valid." : "HTTP " + response.status));
  }
  return data;
}

export function toolPath(thread, tool, item) {
  return "/trip/" + encodeURIComponent(thread) + "/" + tool + (item ? "/" + encodeURIComponent(item) : "");
}
