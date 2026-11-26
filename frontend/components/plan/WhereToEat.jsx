// Restaurants split into vegetarian, non-vegetarian and "menu not specified".
const dot = (list, place) => {
  if (list !== "nonveg") return list;                     // "v" or "u" for the whole list
  return place.serves === "nonveg" ? "n" : place.serves === "veg" ? "v" : "u";
};
const DOT_LIST = { veg: "v", nonveg: "nonveg", other: "u" };

function EatList({ title, places, kind }) {
  if (!places?.length) return null;
  return (
    <div className="card" style={{ margin: 0 }}>
      <b>{title}</b>
      {places.map((place, i) => (
        <div className="eat" key={place.name}>
          <span className={`vd ${dot(DOT_LIST[kind], place)}`} /><span className="rank">{i + 1}</span><b>{place.name}</b>
          {place.serves === "both" && <> <span className="badge">veg &amp; non-veg</span></>}
          {place.cuisine && <span className="muted"> · {place.cuisine}</span>}
          <div className="when">🕒 {place.hours}<br />Best: {place.best_time}</div>
          {place.desc && <div className="muted" style={{ fontSize: 13 }}>{place.desc}</div>}
        </div>
      ))}
    </div>
  );
}

export default function WhereToEat({ dining }) {
  const { veg = [], nonveg = [], other = [], note = "" } = dining || {};
  const split = veg.length > 0 || nonveg.length > 0;
  if (!split && !other.length) {
    if (!note) return null;
    return (
      <div className="card muted"><b>Where to eat</b><p style={{ margin: "6px 0 0" }}>{note}</p></div>
    );
  }
  return (
    <div className="card">
      <b>Where to eat</b> <span className="badge">top picks</span>
      {split && (
        <div className="grid2" style={{ marginTop: 10 }}>
          <EatList title="🟢 Vegetarian" places={veg} kind="veg" />
          <EatList title="🔴 Non-vegetarian" places={nonveg} kind="nonveg" />
        </div>
      )}
      {other.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <EatList title={split ? "More places (menu not specified)" : "Restaurants (menu not specified)"}
            places={other} kind="other" />
        </div>
      )}
      <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>{note}</p>
    </div>
  );
}
