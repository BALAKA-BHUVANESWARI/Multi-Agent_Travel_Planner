// Estimated emissions of getting there and back, for each way of travelling.
import { MODE_ICON } from "../../services/constants.js";
import Banner from "../common/Banner.jsx";
import { LinkList } from "../common/Links.jsx";

function ModeRow({ mode, largest }) {
  if (!mode.available) {
    return <div className="muted" style={{ padding: "4px 0" }}>{MODE_ICON[mode.mode]} {mode.label}: {mode.reason}</div>;
  }
  return (
    <>
      <div className="co2">
        <b>{MODE_ICON[mode.mode]} {mode.label}</b>
        <div className="track">
          <span className={mode.lowest ? "low" : ""} style={{ width: `${Math.max(2, (mode.kg_pp / largest) * 100)}%` }} />
        </div>
        <span style={{ textAlign: "right" }}>{String(mode.kg_pp)} kg</span>
      </div>
      <div className="muted" style={{ fontSize: 13, margin: "-2px 0 4px" }}>
        {mode.basis}{mode.fuel_only_kg_pp ? ` (${mode.fuel_only_kg_pp} kg from fuel alone)` : ""} · about{" "}
        {String(mode.hours)} h each way {mode.selected && <span className="badge">your plan</span>}
        {mode.lowest && <> <span className="badge live">lowest emissions</span></>}
      </div>
    </>
  );
}

export default function FootprintTab({ data }) {
  if (!data.available) return <Banner kind="warn">{data.reason}</Banner>;
  const largest = Math.max(...data.modes.filter((m) => m.available).map((m) => m.kg_pp), 1);
  return (
    <>
      <h4>Getting there and back · per person <span className="badge">estimated</span></h4>
      {data.modes.map((mode) => <ModeRow key={mode.mode} mode={mode} largest={largest} />)}
      {data.advice.map((advice, i) => <Banner kind="ok" key={i}>{advice}</Banner>)}
      <h4>Lighter travel</h4>
      <ul>{data.tips.map((tip, i) => <li key={i}>{tip}</li>)}</ul>
      <details>
        <summary>How these are calculated</summary>
        <p className="muted" style={{ fontSize: 13 }}>{data.method}</p>
        <p className="muted" style={{ fontSize: 13 }}>kg of CO₂ or CO₂-equivalent. Sources: <LinkList links={data.sources} /></p>
      </details>
    </>
  );
}
