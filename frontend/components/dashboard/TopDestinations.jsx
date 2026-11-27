import { INDIA_DESTINATIONS } from "../../services/indiaDestinations.js";
import DestinationGrid from "./DestinationGrid.jsx";

export default function TopDestinations({ chosen, onPick, onWorld }) {
  return (
    <section className="card" id="top10">
      <div className="section-head">
        <h2>Top 10 Destinations in India</h2>
        <span className="muted">Popular picks, not an official ranking. Best months are a rough guide.</span>
        <button type="button" className="link" id="toWorld" onClick={onWorld}>See world destinations →</button>
      </div>
      <DestinationGrid places={INDIA_DESTINATIONS} region="state" chosen={chosen} onPick={onPick} />
    </section>
  );
}
