// Human approval: nothing is booked until the traveller approves.
import { useState } from "react";

const inputStyle = { flex: 1, minWidth: 0, padding: 8 };

export default function DecisionCard({ approval, onDecide }) {
  const [feedback, setFeedback] = useState("");
  const canRevise = Boolean(approval?.can_revise);
  return (
    <div className="card">
      <b>Your decision</b>
      <p className="muted" style={{ margin: "4px 0 10px" }}>
        Nothing is booked until you approve. Try “make it cheaper”, “budget 80000”, “make it 4 days”, “add 1 person”,
        “move it to January”, “go by train”, “change destination to Jaipur”, “skip water sports”, “more food” or
        “relaxed pace”.
      </p>
      <div className="row">
        <button className="primary" id="approve" onClick={() => onDecide({ action: "approve" })}>
          Approve &amp; book (mock)
        </button>
        <button className="danger" id="cancel" onClick={() => onDecide({ action: "cancel" })}>Cancel</button>
      </div>
      <div className="row" style={{ marginTop: 10, flexWrap: "nowrap" }}>
        <input id="fb" style={inputStyle} disabled={!canRevise} value={feedback}
          placeholder={canRevise ? "Request changes…" : "Revision limit reached"} aria-label="Request changes"
          onChange={(e) => setFeedback(e.target.value)} />
        <button id="revise" disabled={!canRevise}
          onClick={() => feedback.trim() && onDecide({ action: "revise", feedback: feedback.trim() })}>
          Request changes
        </button>
      </div>
      <p className="muted" style={{ margin: "6px 0 0", fontSize: 13 }}>
        {approval ? approval.revisions_left : 0} revision(s) left
      </p>
    </div>
  );
}
