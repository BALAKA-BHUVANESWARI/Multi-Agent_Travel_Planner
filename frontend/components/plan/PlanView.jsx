// A finished plan, top to bottom.
import { usePlanPhotos } from "../../hooks/usePlanPhotos.js";
import { MODE_NAME } from "../../services/constants.js";
import { placeName } from "../../services/format.js";
import Banner from "../common/Banner.jsx";
import Toolkit from "../toolkit/Toolkit.jsx";
import AgentLog from "./AgentLog.jsx";
import BookingCard from "./BookingCard.jsx";
import BudgetCard from "./BudgetCard.jsx";
import DayCard from "./DayCard.jsx";
import DecisionCard from "./DecisionCard.jsx";
import GoodToKnow from "./GoodToKnow.jsx";
import GroupFit from "./GroupFit.jsx";
import MapCard from "./MapCard.jsx";
import PlaceCards from "./PlaceCards.jsx";
import TopSights from "./TopSights.jsx";
import TravelAndHotel from "./TravelAndHotel.jsx";
import TripSummary from "./TripSummary.jsx";
import WhereToEat from "./WhereToEat.jsx";

export default function PlanView({ result, onDecide, onRun, onResult, onPickPlace, onSignIn }) {
  const travelMode = result.flight?.selected?.mode || "flight";
  const travelWord = MODE_NAME[travelMode] || "Flight";
  const journeyWarning = result.flight?.selected && result.flight.journey?.warning;
  const activities = result.activities || {};
  const alternatives = result.alternatives?.items || [];
  const waiting = result.status === "awaiting_approval";
  const photos = usePlanPhotos(result);
  const destination = placeName(result.constraints, "destination");
  return (
    <>
      <TripSummary result={result} />
      {[...new Set(result.warnings || [])].map((warning) => <Banner kind="warn" key={warning}>{warning}</Banner>)}
      {journeyWarning && <Banner kind="warn">{journeyWarning}</Banner>}
      <BudgetCard report={result.budget_report} travelWord={travelWord} />
      <GroupFit report={result.group_report} />
      <TravelAndHotel transport={result.flight} hotel={result.hotel} travelWord={travelWord} />
      <div className="muted" style={{ margin: "14px 0 -6px" }}>Weather: {result.weather?.source || "unavailable"}</div>
      {result.itinerary.days.map((day) => (
        <DayCard key={day.day} day={day} travelMode={travelMode} destination={destination}
          country={result.constraints.destination_geo?.country || ""} photos={photos} />
      ))}
      <MapCard itinerary={result.itinerary} centre={result.constraints.destination_geo} />
      <TopSights activities={activities} itinerary={result.itinerary} />
      <WhereToEat dining={activities.dining} />
      <GoodToKnow activities={activities} />
      {waiting && alternatives.length > 0 && (
        <details className="card" open={result.budget_report.over_budget || undefined}>
          <summary>Other places that could work (estimates only)</summary>
          <div style={{ marginTop: 10 }}>
            <PlaceCards items={alternatives} baseline={result.alternatives.baseline} onPick={onPickPlace} />
          </div>
        </details>
      )}
      {result.status === "booked" && <BookingCard result={result} onResult={onResult} onRun={onRun} />}
      {waiting && <DecisionCard approval={result.pending_approval} onDecide={onDecide} />}
      <Toolkit thread={result.thread_id} onSignIn={onSignIn} />
      <AgentLog log={result.log} metrics={result.metrics} />
    </>
  );
}
