// For the sights of the shown plan: which article each one's photos come from. Asked again only when the sights change.
import { useEffect, useState } from "react";
import { api } from "../services/api.js";

export function usePlanPhotos(result) {
  const thread = result.thread_id;
  const sights = result.itinerary.days.flatMap((d) => d.items.filter((i) => i.type === "activity").map((i) => i.id));
  const key = `${thread}|${sights.join(",")}`;
  const [found, setFound] = useState({ key: "", byId: {}, state: "loading" });
  useEffect(() => {
    let stale = false;
    api("/photos", { thread_id: thread })
      .then((data) => !stale && setFound({ key, byId: data.photos || {}, state: data.checked ? "done" : "failed" }))
      .catch(() => !stale && setFound({ key, byId: {}, state: "failed" }));
    return () => {
      stale = true;
    };
  }, [key, thread]);
  return found.key === key ? found : { byId: {}, state: "loading" };
}
