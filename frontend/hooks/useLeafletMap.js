// A Leaflet map inside `boxRef`, showing the planned stops of one day (0 = all days).
import { useEffect, useRef, useState } from "react";
import { escapeHtml } from "../services/format.js";

export const DAY_COLORS = ["#2b6cb0", "#dd6b20", "#38a169", "#805ad5", "#c53030", "#0987a0", "#b7791f", "#d53f8c",
  "#4a5568", "#2f855a", "#9c4221", "#553c9a", "#285e61", "#702459"];

export function useLeafletMap(boxRef, stops, day, centre) {
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    const L = window.L;
    if (!L) {
      setUnavailable(true);
      return undefined;
    }
    const map = L.map(boxRef.current, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [boxRef]);

  useEffect(() => {
    const L = window.L;
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!L || !map) return;
    layer.clearLayers();
    const shown = stops.filter((s) => !day || s.day === day);
    shown.forEach((s) => {
      L.circleMarker([s.lat, s.lon], { radius: 9, color: "#fff", weight: 2,
        fillColor: DAY_COLORS[(s.day - 1) % DAY_COLORS.length], fillOpacity: 0.95 })
        .bindTooltip(escapeHtml(`${day ? s.order + ". " : "Day " + s.day + ": "}${s.name}`))
        .bindPopup(escapeHtml(`Day ${s.day}, ${s.start} · ${s.name}`))
        .addTo(layer);
    });
    if (day && shown.length > 1) {
      L.polyline(shown.map((s) => [s.lat, s.lon]),
        { color: DAY_COLORS[(day - 1) % DAY_COLORS.length], weight: 3, dashArray: "6 6" }).addTo(layer);
    }
    if (shown.length) map.fitBounds(L.latLngBounds(shown.map((s) => [s.lat, s.lon])).pad(0.2), { maxZoom: 15 });
    else if (typeof centre?.lat === "number") map.setView([centre.lat, centre.lon], 12);
    else map.setView([20, 78], 4);
    // `stops` is rebuilt on every render from the same plan, so the day is what changes what is drawn
  }, [day]); // eslint-disable-line react-hooks/exhaustive-deps

  return unavailable;
}
