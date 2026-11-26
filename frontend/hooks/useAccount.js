// Who is signed in, and what the server says about itself.
import { useCallback, useEffect, useState } from "react";
import { api, session } from "../services/api.js";

export function useAccount() {
  const [user, setUser] = useState(null);
  const [health, setHealth] = useState(null);

  const signIn = useCallback((token, nextUser) => {
    session.setToken(token);
    setUser(nextUser);
  }, []);
  const forget = useCallback(() => signIn("", null), [signIn]);
  const signOut = useCallback(async () => {
    try {
      await api("/auth/logout", {});
    } catch {
      // signed out on this device even if the server could not be reached
    }
    forget();
  }, [forget]);

  useEffect(() => {
    session.onExpired(forget);
    if (session.token) api("/me").then((r) => setUser(r.user)).catch(forget);
    api("/health").then(setHealth).catch(() => {});
  }, [forget]);

  return { user, health, authRequired: Boolean(health?.auth_required), signIn, signOut, forget };
}
