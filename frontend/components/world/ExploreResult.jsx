// What the agents found for one place: its picture, the top sights with pictures, and what each agent did.
import Photo from "../dashboard/Photo.jsx";

const ART = { Beach: "beach", Historical: "monument", Spiritual: "monument", Museum: "monument", Nature: "water",
  Waterfall: "water" };

export default function ExploreResult({ result, onPlan }) {
  const { place, sights, notes, attribution, log } = result;
  const where = [place.region !== place.name && place.region, place.country !== place.name && place.country]
    .filter(Boolean).join(", ");
  return (
    <section className="card" id="exploreResult">
      <div className="explore-head">
        <Photo titles={place.photo ? [place.photo] : null} alt={place.name} />
        <div>
          <h2>{place.name}</h2>
          {where && <span className="muted">{where}</span>}
          <button type="button" className="primary" id="planExplored"
            onClick={() => onPlan({ name: place.name })}>Plan a trip to {place.name}</button>
        </div>
      </div>
      {sights.length > 0 && (
        <>
          <h3>Places to see in {place.name}</h3>
          <ul className="places">
            {sights.map((s) => (
              <li key={s.name}>
                <Photo titles={s.photo ? [s.photo] : null} art={ART[s.label] || "mountain"} alt={s.name} />
                <div className="place-body">
                  <h3>{s.name}</h3>
                  <span className="facts"><span>{s.label}</span></span>
                  {s.desc && <span className="muted">{s.desc}</span>}
                  <span className="muted">When to go: {s.best_time}{s.season ? `. ${s.season}` : ""}</span>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      <ul className="explore-notes muted">{notes.map((note) => <li key={note}>{note}</li>)}</ul>
      {attribution.length > 0 && <p className="muted explore-sources">Sources: {attribution.join(" · ")}</p>}
      <details>
        <summary>What the agents did</summary>
        <ol>{log.map((step) => <li key={step.agent}><b>{step.agent}:</b> {step.text}</li>)}</ol>
      </details>
    </section>
  );
}
