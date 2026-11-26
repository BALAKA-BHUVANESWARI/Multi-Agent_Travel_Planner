// Whatever the planner answered: a question back (travel mode, destination) or a plan.
import { NO_PLAN_STATUSES } from "../../services/constants.js";
import { requestFor, withDestination, withTravelMode } from "../../services/tripText.js";
import PlaceCards from "./PlaceCards.jsx";
import PlanView from "./PlanView.jsx";
import TravelChoices from "./TravelChoices.jsx";

export default function PlanResult({ result, lastRequest, onPlan, onDecide, onRun, onResult, onSignIn }) {
  const pickPlace = (baseRequest) => (name) => {
    onPlan(withDestination(baseRequest, name), result.group);
  };

  if (NO_PLAN_STATUSES.includes(result.status)) {
    if (result.travel_options?.length) {
      return (
        <TravelChoices options={result.travel_options}
          onPick={(mode) => onPlan(withTravelMode(lastRequest, mode), result.group)} />
      );
    }
    if (result.suggestions?.length) {
      return (
        <>
          <PlaceCards items={result.suggestions} onPick={pickPlace(result.request)} />
          <p className="muted">Or type any other city or town in your request.</p>
        </>
      );
    }
    return null;
  }
  return (
    <PlanView result={result} onDecide={onDecide} onRun={onRun} onResult={onResult} onSignIn={onSignIn}
      onPickPlace={pickPlace(requestFor(result.constraints))} />
  );
}
