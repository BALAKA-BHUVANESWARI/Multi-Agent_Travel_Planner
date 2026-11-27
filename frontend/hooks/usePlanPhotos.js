// For the sights of the shown plan: which article each one's photos come from, and the destination's own article.
// Asked again only when the sights change.
import { useEffect, useState } from "react";
import { api } from "../services/api.js";

export function usePlanPhotos(result) {
  const thread = result.thread_id;
  const sights = result.itinerary.days.flatMap((d) => d.items.filter((i) => i.type === "activity").map((i) => i.id));
  const key = `${thread}|${sights.join(",")}`;
  const [found, setFound] = useState({ key: "", byId: {}, town: null, state: "loading" });
  useEffect(() => {
    let stale = false;
    api("/photos", { thread_id: thread })
      .then((data) => !stale && setFound({
        key, byId: data.photos || {}, town: data.place || null, state: data.checked ? "done" : "failed",
      }))
      .catch(() => !stale && setFound({ key, byId: {}, town: null, state: "failed" }));
    return () => {
      stale = true;
    };
  }, [key, thread]);
  return found.key === key ? found : { byId: {}, town: null, state: "loading" };
}
