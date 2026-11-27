// The dashboard's calls to the backend. The sign-in lasts for this browser tab only.
import { useEffect, useState } from "react";

const BASE = "/api/v1/dashboard/";
const KEY = "tp_dashboard_token";

function read() {
  try {
    return sessionStorage.getItem(KEY) || "";
  } catch {
    return "";
  }
}

let token = read();
let signedOut = () => {};

export const session = {
  get token() {
    return token;
  },
  set(value) {
    token = value;
    try {
      if (value) sessionStorage.setItem(KEY, value);
      else sessionStorage.removeItem(KEY);
    } catch {
      // not saved: signed in until the page is reloaded
    }
  },
  onSignedOut(handler) {
    signedOut = handler;
  },
};

export function address(path, params = {}) {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null)).toString();
  return BASE + path + (query ? "?" + query : "");
}

async function send(url, options = {}) {
  const sent = token;
  const headers = { ...options.headers, ...(sent ? { Authorization: "Bearer " + sent } : {}) };
  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch {
    throw new Error("The server did not answer. Is it still running?");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && sent && sent === token) {
      session.set("");
      signedOut();
    }
    const error = new Error(data.error || "HTTP " + response.status);
    error.status = response.status;
    throw error;
  }
  return response;
}

export const getJson = async (path, params) => (await send(address(path, params))).json();

export const postJson = async (path, body) =>
  (await send(BASE + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();

export async function download(params) {
  const response = await send(address("export", params));
  const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") || "")?.[1] || "metrics.txt";
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await response.blob());
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 10000);
}

// Loads one view; reloads when the address or `tick` changes, keeping the last answer on screen meanwhile.
export function useData(path, params, tick) {
  const url = address(path, params);
  const [state, setState] = useState({ url: "", data: null, error: "" });
  useEffect(() => {
    let current = true;
    getJson(path, params).then(
      (data) => current && setState({ url, data, error: "" }),
      (e) => current && setState((s) => ({ url, data: s.url === url ? s.data : null, error: e.message })),
    );
    return () => {
      current = false;
    };
  }, [url, tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const samePage = state.url.split("?")[0] === url.split("?")[0];
  return { data: samePage ? state.data : null, error: state.url === url ? state.error : "", loading: state.url !== url };
}
