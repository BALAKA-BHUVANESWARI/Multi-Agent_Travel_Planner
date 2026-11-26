// Where the traveller describes the trip.
import { SAMPLE_REQUESTS } from "../../services/constants.js";

const shorten = (text) => (text.length > 46 ? text.slice(0, 46) + "…" : text);

export default function PromptCard({ text, onText, onPlan, busy, children }) {
  return (
    <div className="card">
      <textarea id="prompt" maxLength={1000} value={text} onChange={(e) => onText(e.target.value)}
        aria-label="Describe your trip"
        placeholder="e.g. Plan a 5 day trip to Bangkok from Mumbai in January, budget 1.8 lakh for 2, love food and temples" />
      <div className="row" style={{ marginTop: 8 }}>
        <button className="primary" id="go" disabled={busy} onClick={() => text.trim() && onPlan(text.trim())}>
          Plan my trip
        </button>
        {busy && <span id="busy" className="muted">Agents working…</span>}
      </div>
      <div className="row chips" id="samples" style={{ marginTop: 10 }}>
        {SAMPLE_REQUESTS.map((sample) => (
          <button key={sample} title={sample} onClick={() => onText(sample)}>{shorten(sample)}</button>
        ))}
      </div>
      {children}
    </div>
  );
}
