// Destinations the planner suggests, or alternatives to the planned one (compared against `baseline`).
import { inr } from "../../services/format.js";

const smallMuted = { fontSize: 13 };

export default function PlaceCards({ items, baseline, onPick }) {
  return (
    <div className="grid2">
      {items.map((place) => (
        <div className="card" style={{ margin: 0 }} key={place.slug}>
          <b>{place.name}</b> <span className="muted">{place.country}</span> <span className="badge">estimated</span>
          <div className="muted" style={smallMuted}>
            {place.tags.join(" · ")} · {place.in_season ? "good time to go" : "off season"}
          </div>
          From about <b>{inr(place.estimate_from)}</b> · comfortable {inr(place.estimate_comfortable)}
          {baseline && (
            <div className="muted" style={smallMuted}>
              {place.estimate_from <= baseline.from
                ? inr(baseline.from - place.estimate_from) + " less"
                : inr(place.estimate_from - baseline.from) + " more"} than your current place at the cheapest level
            </div>
          )}
          {!place.fits_budget && <div style={{ color: "var(--bad)", fontSize: 13 }}>Above your budget</div>}
          <div style={{ marginTop: 8 }}>
            <button data-place={place.name} onClick={() => onPick(place.name)}>Plan {place.name}</button>
          </div>
        </div>
      ))}
    </div>
  );
}
