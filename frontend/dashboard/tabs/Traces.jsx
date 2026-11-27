import { useState } from "react";
import { Card, Empty, Legend, Status, Table } from "../charts.jsx";
import { KINDS, STATUSES, STEP_TYPES, count, facts, ms, sourceName, when, words } from "../format.js";

const COLORS = {
  agent: "var(--series-1)", tool: "var(--series-2)", retrieval: "var(--series-3)", retrieval_wait: "var(--series-3)",
  llm: "var(--series-4)", llm_call: "var(--series-4)", voice: "var(--series-4)", guardrail: "var(--series-5)",
};
const LEGEND = [
  { key: "agent", label: "Agent", color: COLORS.agent },
  { key: "tool", label: "Tool call", color: COLORS.tool },
  { key: "retrieval", label: "Data lookup", color: COLORS.retrieval },
  { key: "llm", label: "AI and voice", color: COLORS.llm },
  { key: "guardrail", label: "Safety check", color: COLORS.guardrail },
];

const outcome = (run) => run.attrs.outcome || run.attrs.reply_source || run.attrs.error || "";

export function TraceList({ data }) {
  return (
    <Card title="Requests" note={data.total > data.runs.length ? `The newest ${data.runs.length} of ${count(data.total)}. Narrow the filters to see older ones.` : "Newest first. Open one to see its steps on a timeline."}>
      <Table
        caption="Requests"
        rows={data.runs}
        keyOf={(r) => r.id}
        columns={[
          { title: "Time", show: (r) => <a href={`#traces/${r.id}`}>{when(r.started)}</a> },
          { title: "Type", show: (r) => <>{KINDS[r.kind] || r.kind}{r.attrs.action ? <small> {words(r.attrs.action)}</small> : null}{r.parent_id && <small> from chat</small>}</> },
          { title: "Result", show: (r) => <Status value={r.status} label={STATUSES[r.status]} /> },
          { title: "Outcome", show: (r) => words(outcome(r)) || "–" },
          { title: "Time taken", num: true, show: (r) => ms(r.duration_ms) },
          { title: "Agent runs", num: true, show: (r) => count(r.agents) },
          { title: "AI calls", num: true, show: (r) => count(r.ai_calls) },
          { title: "Lookups", num: true, show: (r) => count(r.lookups) },
          { title: "Failed steps", num: true, show: (r) => count(r.failed_steps) },
          { title: "Replans", num: true, show: (r) => count(r.replans) },
        ]}
      />
    </Card>
  );
}

function Step({ step, scale, open, onToggle }) {
  const left = Math.min((step.start_ms / scale) * 100, 99.6);
  const width = Math.max((step.duration_ms / scale) * 100, 0.4);
  const name = step.type === "retrieval" || step.type === "retrieval_wait" ? sourceName(step.name) : words(step.name);
  return (
    <li className={open ? "open" : undefined}>
      <button className="step" onClick={onToggle} aria-expanded={open}>
        <span className="step-name" style={{ paddingLeft: `${step.depth * 16}px` }}>
          <i style={{ background: COLORS[step.type] || "var(--gray)" }} aria-hidden="true" />
          <span>
            {name}
            <small>{STEP_TYPES[step.type] || step.type}</small>
          </span>
        </span>
        <span className="step-status">{step.status !== "ok" ? <Status value={step.status} /> : null}</span>
        <span className="lane">
          <span className="bar" style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%`, background: COLORS[step.type] || "var(--gray)" }} />
        </span>
        <span className="step-time">{ms(step.duration_ms)}</span>
      </button>
      {open && (
        <div className="step-detail">
          <dl className="facts">
            <dt>Started</dt>
            <dd>{ms(step.start_ms)} after the request began</dd>
            <dt>Status</dt>
            <dd>{words(step.status)}</dd>
            {facts(step.attrs).map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}
          </dl>
          {step.texts.map((t, i) => (
            <figure key={i}>
              <figcaption>{words(t.name)}</figcaption>
              <pre>{t.text}</pre>
            </figure>
          ))}
        </div>
      )}
    </li>
  );
}

export function TraceDetail({ data }) {
  const [open, setOpen] = useState(() => new Set());
  const { run, steps } = data;
  const scale = Math.max(data.timeline_ms, 1);
  const toggle = (id) => setOpen((old) => (old.has(id) ? new Set([...old].filter((x) => x !== id)) : new Set([...old, id])));
  return (
    <>
      <p>
        <a href="#traces">← All requests</a>
      </p>
      <Card title={`${KINDS[run.kind] || run.kind} · ${when(run.started)}`}>
        <dl className="facts">
          <dt>Result</dt>
          <dd><Status value={run.status} label={STATUSES[run.status]} /></dd>
          <dt>Time taken</dt>
          <dd>{ms(run.duration_ms)}{data.timeline_ms > (run.duration_ms || 0) * 1.05 ? ` (a slow lookup finished later, at ${ms(data.timeline_ms)})` : ""}</dd>
          <dt>Engine</dt>
          <dd>{run.engine || "–"}</dd>
          {facts(run.attrs).map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}
          <dt>Request id</dt>
          <dd><code>{run.id}</code></dd>
          {run.trip && [<dt key="t">Trip id</dt>, <dd key="d"><code>{run.trip}</code></dd>]}
        </dl>
        {data.linked.length > 0 && (
          <>
            <h3>Linked requests (same trip, or started from chat)</h3>
            <ul className="linked">
              {data.linked.map((r) => (
                <li key={r.id}>
                  <a href={`#traces/${r.id}`}>{when(r.started)} · {KINDS[r.kind] || r.kind}{r.attrs.action ? ` (${words(r.attrs.action)})` : ""}</a> <Status value={r.status} label={STATUSES[r.status]} /> {ms(r.duration_ms)}
                </li>
              ))}
            </ul>
          </>
        )}
        {data.texts.map((t, i) => (
          <figure key={i}>
            <figcaption>{words(t.name)}</figcaption>
            <pre>{t.text}</pre>
          </figure>
        ))}
        {!data.has_texts && <p className="note">No typed text or AI answers were kept for this request. Basic records hold names, times and counts only.</p>}
      </Card>
      <Card
        title="Timeline"
        note="Bars that sit under each other at the same position ran at the same time. Click a step for its details."
        action={steps.length > 0 && <button onClick={() => setOpen(open.size ? new Set() : new Set(steps.map((s) => s.id)))}>{open.size ? "Close all" : "Open all"}</button>}
      >
        {steps.length ? (
          <>
            <Legend series={LEGEND} />
            <div className="scale" aria-hidden="true">
              <span>0</span>
              <span>{ms(scale / 2)}</span>
              <span>{ms(scale)}</span>
            </div>
            <ol className="waterfall">
              {steps.map((s) => (
                <Step key={s.id} step={s} scale={scale} open={open.has(s.id)} onToggle={() => toggle(s.id)} />
              ))}
            </ol>
          </>
        ) : (
          <Empty>This request had no recorded steps (for example, a chat reply made by a fixed rule or a refused request).</Empty>
        )}
      </Card>
    </>
  );
}
