// Picture cards for a hand-picked list of destinations, each with a "Plan this trip" button.
import Photo from "./Photo.jsx";

export default function DestinationGrid({ places, region, chosen, onPick }) {
  return (
    <ul className="places">
      {places.map((d) => (
        <li key={d.name} className={chosen === d.name ? "chosen" : ""}>
          <Photo titles={d.photos} art={d.art} alt={`${d.highlight}, ${d.name}`} />
          <div className="place-body">
            <h3>{d.name}</h3>
            <span className="muted">{d[region]} · {d.highlight}</span>
            <span className="facts"><span>Best {d.best}</span><span>{d.days} days</span></span>
            <button type="button" data-place={d.name} onClick={() => onPick(d)}>Plan this trip</button>
          </div>
        </li>
      ))}
    </ul>
  );
}
