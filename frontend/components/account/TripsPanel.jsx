import { useEffect, useState } from "react";
import { api } from "../../services/api.js";
import { inr } from "../../services/format.js";
import Panel from "./Panel.jsx";

export default function TripsPanel({ onOpenTrip, onClose }) {
  const [trips, setTrips] = useState(null);
  const [message, setMessage] = useState(null);
  const fail = (e) => setMessage({ kind: "bad", text: e.message });

  useEffect(() => {
    let stale = false;
    api("/trips").then((r) => !stale && setTrips(r.trips)).catch((e) => !stale && fail(e));
    return () => {
      stale = true;
    };
  }, []);

  const open = async (thread) => {
    try {
      onOpenTrip(await api("/plan/" + encodeURIComponent(thread)));
    } catch (e) {
      fail(e);
    }
  };

  return (
    <Panel title="My trips" message={message} onClose={onClose}>
      <div id="tripList" className="muted">
        {trips === null && "Loading…"}
        {trips?.length === 0 && "No trips yet."}
        {trips?.map((t) => (
          <div className="trip" key={t.thread_id}>
            <span>
              <b>{t.destination || "?"}</b> from {t.origin || "?"} · {t.start_date} · {String(t.days)} days
              {t.total_inr ? " · " + inr(t.total_inr) : ""}{" "}
              <span className="badge">{String(t.status || "").replace(/_/g, " ")}</span>
            </span>
            <button data-trip={t.thread_id} onClick={() => open(t.thread_id)}>Open</button>
          </div>
        ))}
      </div>
    </Panel>
  );
}
