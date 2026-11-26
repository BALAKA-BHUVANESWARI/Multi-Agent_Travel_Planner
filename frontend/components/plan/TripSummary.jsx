import { placeName } from "../../services/format.js";

export default function TripSummary({ result }) {
  const trip = result.constraints;
  const days = result.itinerary;
  return (
    <div className="card">
      <div className="big">{trip.days}-day trip: {placeName(trip, "origin")} → {placeName(trip, "destination")}</div>
      <div className="muted">
        {days.start_date} to {days.end_date} · {trip.travelers} traveler(s) · strategy <b>{result.strategy}</b>
        {" "}· auto-replans {result.retries}/2 · revisions {result.revisions}/2 · engine {result.engine}
      </div>
    </div>
  );
}
