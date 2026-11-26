const ATTRIBUTION = "Weather data by Open-Meteo.com · Place data and map tiles © OpenStreetMap contributors · " +
  "Sights and local tips from Wikipedia and Wikivoyage (CC BY-SA) · Emergency number sources are shown with each result.";

export default function Footer({ health }) {
  return (
    <footer id="foot">
      Prices are synthetic <b>estimates</b> unless marked <b>live</b>. Booking is a <b>mock</b>; nothing is charged.<br />
      <span id="attr">{ATTRIBUTION}{health ? ` Mode: ${health.mode} · engine: ${health.engine}` : ""}</span>
    </footer>
  );
}
