import { inr } from "../../services/format.js";

// when each activity is in the plan, so a top sight can say "planned Day 2, 09:00"
function plannedTimes(itinerary) {
  const planned = new Map();
  itinerary.days.forEach((day) => day.items.forEach((item) => {
    if (item.type === "activity") planned.set(item.name, `Day ${day.day}, ${item.start}`);
  }));
  return planned;
}

export default function TopSights({ activities, itinerary }) {
  const sights = activities.top_sights || [];
  if (!sights.length) return null;
  const planned = plannedTimes(itinerary);
  return (
    <div className="card">
      <b>Top sights</b> <span className="badge">most prominent first</span>
      {sights.map((sight) => (
        <div className="sight" key={sight.rank}>
          <span className="rank">{sight.rank}</span> <b>{sight.name}</b> <span className="badge">{sight.label}</span>
          <span className="muted"> · {sight.cost ? `${inr(sight.cost)} pp est.` : "free"}</span>
          <div className="when">
            🕒 Best time: {sight.best_time}{sight.season ? ` · ${sight.season}` : ""}
            {planned.has(sight.name) && <> · <b>planned {planned.get(sight.name)}</b></>}
          </div>
        </div>
      ))}
      <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>{activities.top_sights_note || ""}</p>
    </div>
  );
}
