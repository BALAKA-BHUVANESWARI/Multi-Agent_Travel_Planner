// "How would you like to travel?": one card per way of travelling, with price, time and emissions.
import { MODE_ICON } from "../../services/constants.js";
import { inr, shortDay } from "../../services/format.js";

const line = { fontSize: 13, marginTop: 4 };

function Choice({ option, onPick }) {
  if (!option.available) {
    return (
      <div className="card">
        <b>{MODE_ICON[option.mode]} {option.label}</b><br />
        <span className="muted">Not available: {option.reason}</span>
      </div>
    );
  }
  return (
    <div className="card">
      <b>{MODE_ICON[option.mode]} {option.label}</b> <span className="badge">estimated</span>
      {option.usual && <> <span className="badge">your usual</span></>}<br />
      <span className="muted">{option.detail || ""}</span><br />
      About <b>{inr(option.price_pp)}</b> per person round trip · {String(option.duration_h)} h each way
      {typeof option.co2_kg_pp === "number" && (
        <div style={line}>
          🌱 about {String(option.co2_kg_pp)} kg CO₂e per person, there and back (estimate)
          {option.greenest && <> <span className="badge live">lowest emissions</span></>}
        </div>
      )}
      {option.extra_days > 0 && (
        <div style={line}>Leave <b>{shortDay(option.leave_date)}</b> · back home <b>{shortDay(option.home_date)}</b></div>
      )}
      {option.warning && <div className="journey-warn">⚠ {option.warning}</div>}
      {option.note && <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{option.note}</div>}
      <div style={{ marginTop: 8 }}>
        <button className="primary" data-mode={option.mode} onClick={() => onPick(option.mode)}>
          Plan by {option.label.toLowerCase()}
        </button>
      </div>
    </div>
  );
}

export default function TravelChoices({ options, onPick }) {
  return (
    <>
      <div className="grid2">
        {options.map((option) => <Choice key={option.mode} option={option} onPick={onPick} />)}
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <button data-mode="any" onClick={() => onPick("any")}>Any mode: pick the best value for me</button>
      </div>
    </>
  );
}
