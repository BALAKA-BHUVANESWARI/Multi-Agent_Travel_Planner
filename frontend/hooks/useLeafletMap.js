// A Leaflet map inside `boxRef`, showing the planned stops of one day (0 = all days) and, for one day,
// the road route between them in blue.
import { useEffect, useRef, useState } from "react";
import { escapeHtml } from "../services/format.js";
import { restyle, STYLE_URL, VECTOR_ATTRIBUTION } from "../services/mapStyle.js";
import { roadRoute } from "../services/routing.js";

export const DAY_COLORS = ["#2b6cb0", "#dd6b20", "#38a169", "#805ad5", "#c53030", "#0987a0", "#b7791f", "#d53f8c",
  "#4a5568", "#2f855a", "#9c4221", "#553c9a", "#285e61", "#702459"];
const ROUTE_EDGE = "#0b4fb3";
const ROUTE_BLUE = "#4285f4";

function plainTiles(L, map) {
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
}

// English, high-contrast names when the vector map can be drawn; otherwise the standard map (local-language names)
async function addBaseMap(L, map, stillThere, onPlain) {
  try {
    if (!L.maplibreGL) throw new Error("vector map library missing");
    const response = await fetch(STYLE_URL);
    if (!response.ok) throw new Error("map style unavailable");
    const style = restyle(await response.json());
    if (!stillThere()) return;
    L.maplibreGL({ style }).addTo(map);
    map.attributionControl?.addAttribution(VECTOR_ATTRIBUTION);
  } catch {
    if (!stillThere()) return;
    plainTiles(L, map);
    onPlain();
  }
}

export function useLeafletMap(boxRef, stops, day, centre) {
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const [unavailable, setUnavailable] = useState(false);
  const [plain, setPlain] = useState(false);
  const [route, setRoute] = useState({});

  useEffect(() => {
    const L = window.L;
    if (!L) {
      setUnavailable(true);
      return undefined;
    }
    const map = L.map(boxRef.current, { scrollWheelZoom: false, maxZoom: 19 });
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);
    addBaseMap(L, map, () => mapRef.current === map, () => setPlain(true));
    return () => {
      mapRef.current = null;
      map.remove();
    };
  }, [boxRef]);

  useEffect(() => {
    const L = window.L;
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!L || !map) return undefined;
    let stale = false;
    layer.clearLayers();
    const shown = stops.filter((s) => !day || s.day === day);
    const points = shown.map((s) => [s.lat, s.lon]);
    if (shown.length) map.fitBounds(L.latLngBounds(points).pad(0.2), { maxZoom: 15 });
    else if (typeof centre?.lat === "number") map.setView([centre.lat, centre.lon], 12);
    else map.setView([20, 78], 4);

    // the route is drawn in its own group underneath, so the stop markers stay on top
    const lines = L.layerGroup().addTo(layer);
    shown.forEach((s, index) => {
      const below = Boolean(day) && index % 2 === 1; // neighbouring labels take turns, so they overlap less
      L.circleMarker([s.lat, s.lon], { radius: 10, color: "#fff", weight: 3,
        fillColor: DAY_COLORS[(s.day - 1) % DAY_COLORS.length], fillOpacity: 1 })
        // on a single day every stop keeps its highlighted name on the map; with all days it appears on hover
        .bindTooltip(escapeHtml(`${day ? s.order + ". " : "Day " + s.day + ": "}${s.name}`),
          { className: "stop-label", permanent: Boolean(day), direction: below ? "bottom" : "top",
            offset: [0, below ? 10 : -10] })
        .bindPopup(escapeHtml(`Day ${s.day}, ${s.start} · ${s.name}`))
        .addTo(layer);
    });

    if (!day || shown.length < 2) return undefined;
    roadRoute(shown).then((found) => {
      if (stale) return;
      L.polyline(found.line, { color: ROUTE_EDGE, weight: 9, opacity: 0.9, interactive: false }).addTo(lines);
      L.polyline(found.line, { color: ROUTE_BLUE, weight: 5, opacity: 1, interactive: false }).addTo(lines);
      map.fitBounds(L.latLngBounds([...points, ...found.line]).pad(0.12), { maxZoom: 15 });
      setRoute({ day, state: "road", km: found.km, minutes: found.minutes });
    }).catch(() => {
      if (stale) return;
      L.polyline(points, { color: ROUTE_BLUE, weight: 4, dashArray: "8 8", interactive: false }).addTo(lines);
      setRoute({ day, state: "straight" });
    });
    return () => {
      stale = true;
    };
    // `stops` is rebuilt on every render from the same plan, so the day is what changes what is drawn
  }, [day]); // eslint-disable-line react-hooks/exhaustive-deps

  // an answer belongs to the day it was asked for, so another day never shows its distance
  const routable = Boolean(day) && stops.filter((s) => s.day === day).length > 1;
  const current = route.day === day ? route : { state: routable ? "loading" : "none" };
  return { unavailable, plain, route: current };
}
