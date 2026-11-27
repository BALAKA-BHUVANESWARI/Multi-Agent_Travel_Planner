// Which page is open. It is kept in the address (#world), so Back, reload and bookmarks work.
import { useEffect, useState } from "react";

const read = () => (window.location.hash === "#world" ? "world" : "home");

export function usePage() {
  const [page, setPage] = useState(read);
  useEffect(() => {
    const sync = () => setPage(read());
    window.addEventListener("popstate", sync);
    window.addEventListener("hashchange", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("hashchange", sync);
    };
  }, []);
  const open = (next) => {
    if (next !== read()) {
      window.history.pushState(null, "", next === "world" ? "#world" : window.location.pathname);
    }
    setPage(next);
  };
  return [page, open];
}
