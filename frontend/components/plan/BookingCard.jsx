// A (mock) booking, and cancelling it in two steps: see the refund first, then confirm.
import { useState } from "react";
import { api } from "../../services/api.js";
import { inr } from "../../services/format.js";
import Banner from "../common/Banner.jsx";

export default function BookingCard({ result, onResult, onRun }) {
  const [quote, setQuote] = useState(null);
  const [error, setError] = useState("");
  const path = `/booking/${result.thread_id}/cancel`;

  const askForQuote = async () => {
    try {
      const answer = await api(path, { confirm: false });
      if (answer.status !== "confirm_cancellation") {
        onResult(answer);
        return;
      }
      setError("");
      setQuote(answer.terms);
    } catch (e) {
      setQuote(null);
      setError(e.message);
    }
  };

  return (
    <div className="card">
      <b>Your booking</b> <span className="badge">mock</span>
      <p className="muted" style={{ margin: "4px 0 8px" }}>
        {result.booking.booking_id}. Nothing was really booked or charged.
      </p>
      <button className="danger" id="cancelBooking" onClick={askForQuote}>Cancel this booking…</button>
      <div id="cancelBox">
        {error && <Banner kind="bad">{error}</Banner>}
        {quote && (
          <>
            <Banner kind="warn">
              Cancelling now would refund {inr(quote.refund_inr)} of {inr(quote.total_inr)} ({quote.refund_pct}%). {quote.policy}
            </Banner>
            <button className="danger" id="cancelYes" onClick={() => onRun(() => api(path, { confirm: true }))}>
              Yes, cancel the booking
            </button>
          </>
        )}
      </div>
    </div>
  );
}
