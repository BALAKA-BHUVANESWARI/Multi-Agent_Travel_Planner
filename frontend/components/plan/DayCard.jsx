import { MODE_ICON } from "../../services/constants.js";
import { inr } from "../../services/format.js";

function Weather({ weather }) {
  if (!weather) return null;
  const icon = weather.rainy ? "🌧️" : weather.precip_prob >= 35 ? "⛅" : "☀️";
  return (
    <span title={`${weather.precip_prob}% rain chance`}>
      {icon} {weather.tmax ?? "?"}°/{weather.tmin ?? "?"}°C · {weather.precip_prob}%
    </span>
  );
}

function Item({ item, travelMode }) {
  const isActivity = item.type === "activity";
  return (
    <li>
      <span className="t">{item.start}–{item.end}</span>
      <span style={{ flex: 1 }}>
        {!isActivity && (
          <span className="muted">{item.type === "hotel" ? "🏨 " : (MODE_ICON[travelMode] || "✈️") + " "}</span>
        )}
        {item.name}
        {isActivity && item.desc && <div className="muted" style={{ fontSize: 13 }}>{item.desc}</div>}
      </span>
      <span>{isActivity && (item.cost_total ? inr(item.cost_total) : <span className="muted">free</span>)}</span>
    </li>
  );
}

export default function DayCard({ day, travelMode }) {
  return (
    <div className={`card day ${day.rainy ? "rainy" : ""}`}>
      <h3>
        Day {day.day} · {day.date} <span className="badge">{day.kind}</span>
        <span style={{ float: "right", fontWeight: 400, fontSize: 13 }}><Weather weather={day.weather} /></span>
      </h3>
      <ul className="items">
        {day.items.map((item, i) => <Item key={i} item={item} travelMode={travelMode} />)}
      </ul>
      {day.notes.map((note, i) => <p className="note" key={i}>☔ {note}</p>)}
    </div>
  );
}
