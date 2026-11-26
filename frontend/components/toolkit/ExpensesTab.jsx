// What was really spent, compared with the planned budget.
import { useState } from "react";
import { toolPath } from "../../services/api.js";
import { download } from "../../services/download.js";
import { capitalise, inr, longDay, signedInr } from "../../services/format.js";

function Difference({ row, stage }) {
  if (!row.entries) return <td className="muted">–</td>;
  // while the trip is not over, being under the estimate means nothing yet, so only overspending is coloured
  const colour = row.difference > 0 ? "bad" : stage === "final" ? "ok" : "muted";
  return <td style={{ color: `var(--${colour})` }}>{signedInr(row.difference)}</td>;
}

function Comparison({ summary }) {
  const total = summary.total;
  return (
    <>
      <h4>Planned against actual <span className="badge">{summary.stage}</span></h4>
      <div className="tablewrap">
        <table className="money">
          <tbody>
            <tr><th>Category</th><th>Planned</th><th>Spent</th><th>Difference</th></tr>
            {summary.categories.map((row) => (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td>{inr(row.planned)}</td>
                <td>{row.entries ? inr(row.actual) : <span className="muted">–</span>}</td>
                <Difference row={row} stage={summary.stage} />
              </tr>
            ))}
            <tr><th>Total</th><th>{inr(total.planned)}</th><th>{inr(total.actual)}</th><th /></tr>
          </tbody>
        </table>
      </div>
      <p style={{ margin: "8px 0" }}>
        Budget {inr(total.budget)} ·{" "}
        <b style={{ color: `var(--${total.budget_left < 0 ? "bad" : "ok"})` }}>
          {total.budget_left < 0 ? "over by " + inr(-total.budget_left) : inr(total.budget_left) + " left"}
        </b>
        {total.actual ? ` · spent ${inr(total.per_person)} per person` : ""}
      </p>
      <ul>{summary.insights.map((insight, i) => <li key={i}>{insight}</li>)}</ul>
    </>
  );
}

export default function ExpensesTab({ data, thread, onChange }) {
  const [form, setForm] = useState({ category: data.categories[0], amount: "", date: data.today, note: "" });
  const field = (key) => ({ value: form[key], onChange: (e) => setForm((f) => ({ ...f, [key]: e.target.value })) });
  const add = () => onChange(toolPath(thread, "expenses"), { ...form, date: form.date || null });
  const label = (category) => data.labels?.[category] || capitalise(category.replace(/_/g, " "));
  return (
    <>
      <Comparison summary={data.summary} />
      <h4>Add an expense</h4>
      <p className="muted" style={{ margin: "4px 0", fontSize: 13 }}>{data.summary.note}</p>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <label className="field">Category
          <select id="exCat" {...field("category")}>
            {data.categories.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </select>
        </label>
        <label className="field">Amount (₹)
          <input id="exAmount" inputMode="decimal" maxLength={12} {...field("amount")}
            onKeyDown={(e) => e.key === "Enter" && add()} />
        </label>
        <label className="field">Date<input type="date" id="exDate" {...field("date")} /></label>
        <label className="field">Note (optional)<input id="exNote" maxLength={120} {...field("note")} /></label>
        <button type="button" className="primary" id="exAdd" onClick={add}>Add</button>
      </div>
      {data.entries.map((entry) => (
        <div className="trip" key={entry.id}>
          <span>
            <b>{inr(entry.amount)}</b> {label(entry.category)}{" "}
            <span className="muted">· {longDay(entry.date)}{entry.note ? " · " + entry.note : ""}</span>
          </span>
          <button type="button" data-del={entry.id} aria-label="Delete this expense"
            onClick={() => onChange(toolPath(thread, "expenses", entry.id), null, "DELETE")}>Delete</button>
        </div>
      ))}
      {data.entries.length > 0 && (
        <div style={{ marginTop: 8 }}>
          {/* the leading byte-order mark makes Excel read the file as UTF-8 */}
          <button type="button" id="csvBtn"
            onClick={() => download("trip-expenses.csv", "﻿" + data.csv, "text/csv;charset=utf-8")}>
            Download as CSV
          </button>
        </div>
      )}
    </>
  );
}
