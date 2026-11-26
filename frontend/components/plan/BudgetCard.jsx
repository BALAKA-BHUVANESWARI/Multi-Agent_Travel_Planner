// The total against the budget, split into travel, hotel, activities and food.
import { inr } from "../../services/format.js";

export default function BudgetCard({ report, travelWord }) {
  const lines = report.lines;
  const scale = Math.max(report.total, report.budget) * 1.08 || 1;
  const percent = (amount) => `${(amount / scale) * 100}%`;
  const segment = (key, colour) => (
    <span style={{ width: percent(lines[key]), background: `var(--${colour})` }} title={`${key}: ${inr(lines[key])}`} />
  );
  const legend = (colour, label, amount) => (
    <span><i style={{ background: `var(--${colour})` }} />{label} {inr(amount)}</span>
  );
  const over = report.over_budget;
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <span className="big">{inr(report.total)}</span> <span className="muted">of {inr(report.budget)} budget</span>
          {" "}<span className="badge">estimated</span>
          {report.live?.length > 0 && <> <span className="badge live">{report.live.join(" & ")} live</span></>}
        </div>
        <div style={{ color: `var(--${over ? "bad" : "ok"})`, fontWeight: 600 }}>
          {over ? "Over by " + inr(report.total - report.budget) : inr(report.remaining) + " left"}
        </div>
      </div>
      <div className="bar" style={{ marginTop: 10 }}>
        {segment("flight", "flight")}{segment("hotel", "hotel")}{segment("activities", "acts")}{segment("food", "food")}
        <div className="marker" style={{ left: percent(report.budget) }} title="budget" />
      </div>
      <div className="legend">
        {legend("flight", travelWord, lines.flight)}
        {legend("hotel", "Hotel", lines.hotel)}
        {legend("acts", "Activities", lines.activities)}
        {legend("food", "Food", lines.food)}
        <span className="muted">{inr(report.per_person)} per person</span>
      </div>
    </div>
  );
}
