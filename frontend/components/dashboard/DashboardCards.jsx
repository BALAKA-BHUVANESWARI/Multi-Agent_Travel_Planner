// The three boxes under the destinations: the current itinerary, travel tips and the chosen travel style.
import { capitalise, inr, MONTH_NAMES, placeName } from "../../services/format.js";
import { findDestination, INDIA_DESTINATIONS } from "../../services/indiaDestinations.js";
import { NO_PLAN_STATUSES } from "../../services/constants.js";
import Icon from "./Icon.jsx";
import Photo, { Drawing } from "./Photo.jsx";

function Itinerary({ result, onView, onStart }) {
  const plan = result?.itinerary && !NO_PLAN_STATUSES.includes(result.status) ? result : null;
  const name = plan ? placeName(plan.constraints, "destination") : "";
  const known = findDestination(name);
  const total = plan?.budget_report?.total;
  return (
    <section className="card tile" id="itineraryTile">
      <div className="section-head">
        <h2>Your Personalised Itinerary</h2>
        {plan && <button type="button" className="link" id="viewPlan" onClick={onView}>View details →</button>}
      </div>
      {/* outside the ten places a name alone could match the wrong article, so only the drawing is shown */}
      <Photo titles={plan ? known?.photos : ["Hawa Mahal"]} art={known?.art || "mountain"}
        alt={plan ? name : "Hawa Mahal, Jaipur"} className="wide" />
      {plan ? (
        <>
          <h3>{plan.constraints.days}-day trip to {name}</h3>
          <p className="muted">
            From {placeName(plan.constraints, "origin")} · {plan.itinerary.start_date} to {plan.itinerary.end_date} ·{" "}
            {plan.constraints.travelers} traveller(s)
          </p>
          <ul className="ticks">
            <li><Icon name="check" size={14} />{plan.itinerary.days.length} days planned</li>
            {typeof total === "number" && <li><Icon name="check" size={14} />About {inr(total)} in total</li>}
            <li><Icon name="check" size={14} />Status: {plan.status.replace(/_/g, " ")}</li>
          </ul>
        </>
      ) : (
        <>
          <h3>Your trip will appear here</h3>
          <p className="muted">Pick a destination above or fill in the form.</p>
          <button type="button" className="primary" onClick={onStart}>Start planning</button>
        </>
      )}
    </section>
  );
}

function Insights({ date }) {
  // with no date chosen the planner starts the trip about three weeks from today
  const month = date ? Number(date.split("-")[1]) : new Date(Date.now() + 21 * 86400000).getMonth() + 1;
  const good = INDIA_DESTINATIONS.filter((d) => d.months.includes(month)).map((d) => d.name);
  return (
    <section className="card tile" id="insights">
      <div className="section-head"><h2>Travel Insights</h2></div>
      <div className="tip warm">
        <Icon name="bulb" />
        <span>
          <b>{good.length ? `Good in ${MONTH_NAMES[month - 1]}:` : `${MONTH_NAMES[month - 1]} is off season:`}</b>{" "}
          {good.length ? good.join(", ") : "none of the ten places above is at its best"} (rough guide).
        </span>
      </div>
      <div className="tip"><Icon name="wallet" /><span>Prices are estimates unless a plan marks them <b>live</b>.</span></div>
      <div className="tip"><Icon name="check" /><span>Nothing is booked until you approve, and booking is a mock.</span></div>
    </section>
  );
}

const STYLES = [
  ["Adventurer", ["adventure", "nature"]],
  ["Beach lover", ["beach", "relaxation"]],
  ["Culture seeker", ["history", "culture", "spiritual"]],
  ["Foodie", ["food"]],
  ["City explorer", ["shopping", "nightlife"]],
  ["Family traveller", ["family"]],
];

function TravelStyle({ interests }) {
  // the style that matches the most chosen interests
  const score = ([, likes]) => likes.filter((i) => interests.includes(i)).length;
  const best = STYLES.reduce((a, b) => (score(b) > score(a) ? b : a));
  const label = score(best) ? best[0] : "Explorer";
  return (
    <section className="card tile style-tile">
      <Drawing kind="mountain" />
      <div>
        <h2>Your Travel Style</h2>
        <span className="style-name" id="styleName">{label}</span>
        <p>
          {interests.length ? `You like ${interests.map((i) => capitalise(i).toLowerCase()).join(", ")}.`
            : "Choose what you like in the form and your plan will lean that way."}
        </p>
      </div>
    </section>
  );
}

export default function DashboardCards({ result, date, interests, onView, onStart }) {
  return (
    <div className="tiles">
      <Itinerary result={result} onView={onView} onStart={onStart} />
      <Insights date={date} />
      <TravelStyle interests={interests} />
    </div>
  );
}
