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

// open on the first day that has a route to show
const firstRouteDay = (itinerary, stops) =>
  itinerary.days.find((d) => stops.filter((s) => s.day === d.day).length > 1)?.day ?? 0;

const duration = (minutes) => {
  const total = Math.max(1, Math.round(minutes));
  return total < 60 ? `${total} min` : `${Math.floor(total / 60)} h ${total % 60} min`;
};

function RouteNote({ route, day }) {
  if (route.state === "loading") return "Finding the road route…";
  if (route.state === "road") {
    return `Day ${day} route by car, in stop order: about ${route.km.toFixed(1)} km, ${duration(route.minutes)} of ` +
      "driving, without live traffic or time at the stops. Route from OSRM using OpenStreetMap data.";
  }
  if (route.state === "straight") {
    return "The road route could not be loaded, so the dashed blue line only shows the visiting order.";
  }
  return day ? "This day has fewer than two places on the map, so there is no route." : "Choose a day to see its route.";
}

export default function MapCard({ itinerary, centre }) {
  const { stops, missing } = mapStops(itinerary);
  const [day, setDay] = useState(() => firstRouteDay(itinerary, stops));
  const boxRef = useRef(null);
  const { unavailable, plain, route } = useLeafletMap(boxRef, stops, day, centre);

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
      {!unavailable && <p id="routeNote" style={{ margin: "8px 0 0", fontSize: 14 }}><RouteNote route={route} day={day} /></p>}
      <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>
        {plain && "The English map could not be loaded, so this is the standard map with local-language names. "}
        {stops.length} planned stop(s) shown
        {missing ? `; ${missing} without a fixed location (such as a meal or walk) are not on the map` : ""}.
        To draw a route, the positions of that day's sights are sent to the OSRM routing server. Hotels are not plotted because the planner picks a hotel category,
        not a specific property.
      </p>
    </div>
  );
}
