// The planned activities on a map, all days or one day at a time.
import { useRef, useState } from "react";
import { useLeafletMap } from "../../hooks/useLeafletMap.js";

function mapStops(itinerary) {
  const stops = [];
  let missing = 0;
  itinerary.days.forEach((day) => {
    let order = 0;
    day.items.forEach((item) => {
      if (item.type !== "activity") return;
      if (typeof item.lat === "number" && typeof item.lon === "number") {
        stops.push({ day: day.day, order: ++order, name: item.name, start: item.start, lat: item.lat, lon: item.lon });
      } else {
        missing += 1;
      }
    });
  });
  return { stops, missing };
}

export default function MapCard({ itinerary, centre }) {
  const { stops, missing } = mapStops(itinerary);
  const [day, setDay] = useState(0);
  const boxRef = useRef(null);
  const unavailable = useLeafletMap(boxRef, stops, day, centre);

  const dayButton = (value, label) => (
    <button key={value} data-day={value} aria-pressed={day === value} onClick={() => setDay(value)}>{label}</button>
  );
  return (
    <div className="card">
      <b>Map</b> <span className="badge">approximate positions</span>
      <div className="row days" style={{ marginTop: 8 }}>
        {dayButton(0, "All days")}
        {itinerary.days.map((d) => dayButton(d.day, `Day ${d.day}`))}
      </div>
      <div id="map" ref={boxRef}>
        {unavailable && (
          <p className="muted">
            The map library could not be loaded (it needs internet access). The itinerary above is complete without it.
          </p>
        )}
      </div>
      <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>
        {stops.length} planned stop(s) shown
        {missing ? `; ${missing} without a fixed location (such as a meal or walk) are not on the map` : ""}.
        Lines show visiting order, not roads. Hotels are not plotted because the planner picks a hotel category,
        not a specific property.
      </p>
    </div>
  );
}
