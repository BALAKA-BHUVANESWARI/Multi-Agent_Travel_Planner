// The one-line message above the result: what happened, or what the planner needs to know.
import { NO_PLAN_STATUSES } from "../../services/constants.js";
import Banner from "../common/Banner.jsx";

function messageFor(result) {
  if (NO_PLAN_STATUSES.includes(result.status)) {
    if (result.place_check) {
      return ["warn", String(result.message).split(" Reply ")[0] + " Pick one below."];
    }
    if (result.travel_options?.length) {
      const lead = String(result.message || "").split("\n")[0].split(" Reply with")[0] + " Pick one below.";
      return ["warn", lead];
    }
    if (result.suggestions?.length) {
      return ["warn", "You didn't name a destination. Here are some that suit your trip (prices are estimates)."];
    }
    return [result.status === "blocked" ? "bad" : "warn", result.message];
  }
  if (result.status === "booked") return ["ok", `Booked (MOCK): ${result.booking.booking_id}. ${result.booking.status}`];
  return [result.status === "booking_cancelled" ? "warn" : "ok", result.message];
}

export default function PlanMessage({ result, error }) {
  if (!error && !result) return <div id="msg" />;
  const [kind, text] = error ? ["bad", error] : messageFor(result);
  return <div id="msg"><Banner kind={kind}>{text}</Banner></div>;
}
