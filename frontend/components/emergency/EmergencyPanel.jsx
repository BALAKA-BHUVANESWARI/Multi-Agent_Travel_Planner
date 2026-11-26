// "Emergency help" at the top of the page. It works with no plan and without signing in.
import { useRef, useState } from "react";
import Banner from "../common/Banner.jsx";
import EmergencyLookup from "./EmergencyLookup.jsx";

export default function EmergencyPanel({ tripName, thread, onClose }) {
  const [place, setPlace] = useState("");
  const [output, setOutput] = useState(null);
  const asked = useRef(0);

  const ask = (request) => setOutput({ kind: "lookup", request, id: ++asked.current });
  const byPlace = () => place.trim() && ask({ place: place.trim() });
  const byLocation = () => {
    if (!navigator.geolocation) {
      setOutput({ kind: "warn", text: "This browser cannot share a location. Type the town instead." });
      return;
    }
    setOutput({ kind: "waiting" });
    navigator.geolocation.getCurrentPosition(
      (position) => ask({ lat: position.coords.latitude, lon: position.coords.longitude, nearby: true }),
      () => setOutput({ kind: "warn", text: "The location was not shared. Type the town you are in instead." }),
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 60000 });
  };

  return (
    <div className="card" style={{ borderColor: "var(--bad)" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b>Emergency help</b>
        <button type="button" id="sosClose" onClick={onClose}>Close</button>
      </div>
      <p style={{ margin: "6px 0" }}><b>In danger or badly hurt? Call the local emergency number first.</b></p>
      <div className="row">
        <input id="sosPlace" maxLength={80} placeholder="Town or city you are in" aria-label="Town or city you are in"
          value={place} onChange={(e) => setPlace(e.target.value)} onKeyDown={(e) => e.key === "Enter" && byPlace()} />
        <button type="button" className="primary" id="sosShow" onClick={byPlace}>Show numbers</button>
        <button type="button" id="sosHere" onClick={byLocation}>Use my location</button>
        {tripName && <button type="button" id="sosTrip" onClick={() => ask({ thread_id: thread })}>For {tripName}</button>}
      </div>
      <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>
        “Use my location” sends your position to this app's server and to OpenStreetMap's map service to find places
        nearby. The app does not save it.
      </p>
      <div id="sosOut">
        {output?.kind === "waiting" && <p className="muted">Waiting for your browser to share the location…</p>}
        {output?.kind === "warn" && <Banner kind="warn">{output.text}</Banner>}
        {output?.kind === "lookup" && <EmergencyLookup key={output.id} request={output.request} />}
      </div>
    </div>
  );
}
