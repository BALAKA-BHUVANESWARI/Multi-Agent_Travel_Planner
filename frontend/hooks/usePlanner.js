// The current planning result and the actions that change it.
import { useCallback, useRef, useState } from "react";
import { api } from "../services/api.js";

export function usePlanner(readMembers) {
  // `version` goes up with every new result, so the screen below it starts fresh (open boxes and typed text reset)
  const [view, setView] = useState({ result: null, version: 0, error: "" });
  const [busy, setBusy] = useState(false);
  const lastRequest = useRef("");

  const show = useCallback((result) => setView((v) => ({ result, version: v.version + 1, error: "" })), []);
  const clear = useCallback(() => setView((v) => ({ result: null, version: v.version + 1, error: "" })), []);
  const fail = useCallback((e) => setView((v) => ({ ...v, error: e.message })), []);

  // run a request that answers with a new result; the old one stays on screen if it fails
  const run = useCallback(async (request) => {
    setBusy(true);
    try {
      show(await request());
    } catch (e) {
      fail(e);
    }
    setBusy(false);
  }, [show, fail]);

  const plan = useCallback((text, group) => {
    lastRequest.current = text;
    const members = group?.length ? group : readMembers();
    clear();
    return run(() => api("/plan", members.length ? { request: text, group: members } : { request: text }));
  }, [clear, run, readMembers]);

  return { ...view, busy, lastRequest, plan, run, show, clear };
}
