import { MODE_ICON } from "../../services/constants.js";
import { inr } from "../../services/format.js";
import { exampleKind } from "../../services/examplePhotos.js";
import PlacePhotos, { ExamplePhotos, isSight } from "./PlacePhotos.jsx";

function Weather({ weather }) {
  if (!weather) return null;
  const icon = weather.rainy ? "🌧️" : weather.precip_prob >= 35 ? "⛅" : "☀️";
  return (
    <span title={`${weather.precip_prob}% rain chance`}>
      {icon} {weather.tmax ?? "?"}°/{weather.tmin ?? "?"}°C · {weather.precip_prob}%
    </span>
  );
}

function Item({ item, travelMode, destination, country, photos }) {
  const isActivity = item.type === "activity";
  const example = isActivity ? exampleKind(item.id) : null;
  return (
    <li>
      <span className="t">{item.start}–{item.end}</span>
      <span style={{ flex: 1, minWidth: 0 }}>
        {!isActivity && (
          <span className="muted">{item.type === "hotel" ? "🏨 " : (MODE_ICON[travelMode] || "✈️") + " "}</span>
        )}
        {item.name}
        {isActivity && item.desc && <div className="muted" style={{ fontSize: 13 }}>{item.desc}</div>}
        {isSight(item) && (
          <PlacePhotos name={item.name} destination={destination} article={photos.byId[item.id]}
            lookup={photos.state} />
        )}
        {example && (
          <ExamplePhotos name={item.name} destination={destination} country={country} kind={example}
            town={photos.town} lookup={photos.state} />
        )}
      </span>
      <span>{isActivity && (item.cost_total ? inr(item.cost_total) : <span className="muted">free</span>)}</span>
    </li>
  );
}

export default function DayCard({ day, travelMode, destination, country, photos }) {
  return (
    <div className={`card day ${day.rainy ? "rainy" : ""}`}>
      <h3>
        Day {day.day} · {day.date} <span className="badge">{day.kind}</span>
        <span style={{ float: "right", fontWeight: 400, fontSize: 13 }}><Weather weather={day.weather} /></span>
      </h3>
      <ul className="items">
        {day.items.map((item, i) => (
          <Item key={i} item={item} travelMode={travelMode} destination={destination} country={country}
            photos={photos} />
        ))}
      </ul>
      {day.notes.map((note, i) => <p className="note" key={i}>☔ {note}</p>)}
    </div>
  );
}
