// Small charts and tables, drawn with plain HTML so they resize with the page.
import { useState } from "react";
import { count, words } from "./format.js";

// ---------------------------------------------------------------- status: always a mark and a word, never colour alone
const TONES = {
  good: ["ok", "cached", "booked", "approved"],
  warning: ["degraded", "fallback", "blocked", "needs_info", "warnings", "blocking", "not_possible", "warning", "rejected"],
  serious: ["refused", "rate_limited", "gave_up"],
  critical: ["error", "failed", "timeout", "http_error", "network", "unreadable", "schema_invalid"],
};
const MARKS = { good: "✓", warning: "!", serious: "!", critical: "✕", plain: "–" };
export const toneOf = (status) => Object.keys(TONES).find((tone) => TONES[tone].includes(status)) || "plain";

export function Status({ value, label }) {
  const tone = value === "needs_info" || value === "info" ? "plain" : toneOf(value);
  return (
    <span className={`status ${tone}`}>
      <i aria-hidden="true">{MARKS[tone]}</i>
      {label || words(value)}
    </span>
  );
}

// ---------------------------------------------------------------- tiles
export function Tile({ label, value, note }) {
  return (
    <div className="tile">
      <span>{label}</span>
      <b>{value}</b>
      {note && <small>{note}</small>}
    </div>
  );
}

export function Card({ title, note, children, action }) {
  return (
    <section className="card">
      <header>
        <h2>{title}</h2>
        {action}
      </header>
      {note && <p className="note">{note}</p>}
      {children}
    </section>
  );
}

export const Empty = ({ children }) => <p className="empty">{children}</p>;

export const Small = ({ n }) => (n > 0 && n < 5 ? <em className="few" title="Too few to rely on">only {n}</em> : null);

// ---------------------------------------------------------------- tables
// columns: [{ title, show: (row) => node, num: true }]
export function Table({ columns, rows, keyOf, empty = "Nothing recorded for these filters.", caption }) {
  if (!rows.length) return <Empty>{empty}</Empty>;
  return (
    <div className="scroll" tabIndex={0} role="region" aria-label={caption}>
      <table>
        {caption && <caption className="hidden">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.title} className={c.num ? "num" : undefined}>
                {c.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={keyOf ? keyOf(row, i) : i}>
              {columns.map((c) => (
                <td key={c.title} className={c.num ? "num" : c.wide ? "wide" : undefined}>
                  {c.show(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- column chart (one series, or stacked)
function niceTop(value) {
  if (value <= 4) return 4;
  const base = 10 ** Math.floor(Math.log10(value));
  return [1, 2, 4, 5, 8, 10].map((m) => m * base).find((top) => top >= value);
}

export function Legend({ series }) {
  return (
    <ul className="legend">
      {series.map((s) => (
        <li key={s.key}>
          <i style={{ background: s.color }} aria-hidden="true" />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

// data: [{ label, title, values: {key: number} }]
export function Columns({ data, series, format = count, describe }) {
  const [hover, setHover] = useState(null);
  const total = (d) => series.reduce((sum, s) => sum + (d.values[s.key] || 0), 0);
  const top = niceTop(Math.max(...data.map(total), 0));
  const step = Math.max(1, Math.ceil(data.length / 8));
  const shown = hover != null ? data[hover] : null;
  return (
    <div className="chart" role="img" aria-label={describe}>
      <div className="plot" onMouseLeave={() => setHover(null)}>
        <div className="axis" aria-hidden="true">
          {[1, 0.5, 0].map((share) => (
            <span key={share} style={{ bottom: `${share * 100}%` }}>
              {format(top * share)}
            </span>
          ))}
        </div>
        <div className="bars">
          {[1, 0.5].map((share) => (
            <hr key={share} style={{ bottom: `${share * 100}%` }} />
          ))}
          {data.map((d, i) => (
            <div key={i} className="slot" tabIndex={0} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}
              aria-label={`${d.title || d.label}: ${series.map((s) => `${s.label} ${format(d.values[s.key] || 0)}`).join(", ")}`}>
              <div className="stack">
                {series
                  .filter((s) => d.values[s.key])
                  .map((s) => (
                    <div key={s.key} style={{ height: `${(d.values[s.key] / top) * 100}%`, background: s.color }} />
                  ))}
              </div>
            </div>
          ))}
          {shown && (
            <div className="tip" style={{ left: `${((hover + 0.5) / data.length) * 100}%`, transform: `translateX(-${((hover + 0.5) / data.length) * 100}%)` }}>
              <b>{shown.title || shown.label}</b>
              {series
                .filter((s) => series.length === 1 || shown.values[s.key])
                .map((s) => (
                  <span key={s.key}>
                    <i style={{ background: s.color }} />
                    {s.label}: {format(shown.values[s.key] || 0)}
                  </span>
                ))}
            </div>
          )}
        </div>
      </div>
      <div className="xlabels" aria-hidden="true">
        {data.map((d, i) => (
          <span key={i}>{i % step === 0 ? <em>{d.label}</em> : null}</span>
        ))}
      </div>
    </div>
  );
}

// rows: [{ key, label, value, text, color }]
export function Bars({ rows }) {
  const most = Math.max(...rows.map((r) => r.value || 0), 1);
  return (
    <ul className="hbars">
      {rows.map((r) => (
        <li key={r.key}>
          <span>{r.label}</span>
          <div className="track">
            <div style={{ width: `${Math.max(((r.value || 0) / most) * 100, r.value ? 0.8 : 0)}%`, background: r.color || "var(--series-1)" }} />
          </div>
          <b>{r.text}</b>
        </li>
      ))}
    </ul>
  );
}

export function Meter({ label, used, limit }) {
  const share = limit > 0 ? Math.min(used / limit, 1) : used > 0 ? 1 : 0;
  const tone = share >= 1 ? "critical" : share >= 0.8 ? "warning" : "";
  return (
    <li className="meter">
      <span>{label}</span>
      <div className="track" role="meter" aria-valuenow={used} aria-valuemin={0} aria-valuemax={limit} aria-label={label}>
        <div className={tone} style={{ width: `${share * 100}%` }} />
      </div>
      <b>
        {count(used)} of {count(limit)}
        {share >= 1 ? " (limit reached)" : share >= 0.8 ? " (nearly used up)" : ""}
      </b>
    </li>
  );
}
