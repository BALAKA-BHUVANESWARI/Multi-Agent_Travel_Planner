import { INDIA_DESTINATIONS } from "../../services/indiaDestinations.js";
import Photo from "./Photo.jsx";

export default function TopDestinations({ chosen, onPick }) {
  return (
    <section className="card" id="top10">
      <div className="section-head">
        <h2>Top 10 Destinations in India</h2>
        <span className="muted">Popular picks, not an official ranking. Best months are a rough guide.</span>
      </div>
      <ul className="places">
        {INDIA_DESTINATIONS.map((d) => (
          <li key={d.name} className={chosen === d.name ? "chosen" : ""}>
            <Photo titles={d.photos} art={d.art} alt={`${d.highlight}, ${d.name}`} />
            <div className="place-body">
              <h3>{d.name}</h3>
              <span className="muted">{d.state} · {d.highlight}</span>
              <span className="facts"><span>Best {d.best}</span><span>{d.days} days</span></span>
              <button type="button" data-place={d.name} onClick={() => onPick(d)}>Plan this trip</button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
