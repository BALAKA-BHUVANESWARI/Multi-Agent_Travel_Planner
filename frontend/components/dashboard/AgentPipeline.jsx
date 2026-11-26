// Which agents build a plan, and where the current request stands. The server answers once, when the whole run
// is over, so no step-by-step progress or percentage is shown.
import Icon from "./Icon.jsx";

const STAGES = [
  ["search", "Research Agents", "Travel, hotel, weather and sights, in parallel"],
  ["route", "Planner Agent", "Builds the day-by-day itinerary"],
  ["wallet", "Budget Agent", "Adds up costs and looks for cheaper options if over"],
  ["check", "Critic Agent", "Checks the plan before you approve it"],
];

const STATES = {
  idle: ["Ready to plan", "Fill in your trip and press Plan My Trip."],
  working: ["Planning your trip…", "The agents are working."],
  question: ["Your answer is needed", "See the message below."],
  ready: ["Plan ready", "Review it below, then approve or ask for changes."],
  booked: ["Booked (mock)", "Nothing is really charged."],
  stopped: ["No plan yet", "See the message below."],
};

export function pipelineState({ busy, error, result }) {
  if (busy) return "working";
  if (error) return "stopped";
  if (!result) return "idle";
  if (result.status === "needs_info") return "question";
  if (result.status === "booked") return "booked";
  return result.itinerary && !["blocked", "cancelled"].includes(result.status) ? "ready" : "stopped";
}

export default function AgentPipeline({ state }) {
  const done = state === "ready" || state === "booked";
  const [title, note] = STATES[state];
  return (
    <section className={"pipeline " + state} id="pipeline" aria-live="polite">
      <div className="card stages">
        <b>✦ Multi-Agent Planning in Action</b>
        <ol>
          {STAGES.map(([icon, name, text], index) => (
            <li key={name}>
              <span className={"dot d" + index}><Icon name={done ? "check" : icon} size={22} /></span>
              <b>{index + 1}. {name}</b>
              <small>{text}</small>
            </li>
          ))}
        </ol>
      </div>
      <div className="card status" id="agentStatus" data-state={state}>
        <span className="ring">{done && <Icon name="check" size={30} />}</span>
        <b>{title}</b>
        <small>{note}</small>
      </div>
    </section>
  );
}
