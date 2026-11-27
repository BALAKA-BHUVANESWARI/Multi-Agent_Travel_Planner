// The World destinations page: explore any place by name, or pick one of the popular ones.
import { WORLD_DESTINATIONS } from "../../services/worldDestinations.js";
import DestinationGrid from "../dashboard/DestinationGrid.jsx";
import ExplorePlaces from "./ExplorePlaces.jsx";

export default function WorldPage({ chosen, onPick }) {
  return (
    <div id="world">
      <header className="world-head">
        <h1>World Destinations</h1>
        <p>Popular places around the world, and any other place you want to explore.</p>
      </header>
      <ExplorePlaces onPlan={onPick} />
      <section className="card" id="worldTop">
        <div className="section-head">
          <h2>Top World Destinations</h2>
          <span className="muted">Popular picks, not an official ranking. Best months are a rough guide.</span>
        </div>
        <DestinationGrid places={WORLD_DESTINATIONS} region="country" chosen={chosen} onPick={onPick} />
      </section>
    </div>
  );
}
