import { useState } from "react";
import { Card, Columns, Empty, Legend, Meter, Small, Status, Table, Tile } from "../charts.jsx";
import { KINDS, STATUSES, STEP_TYPES, count, ms, percent, shortLabels, when, words } from "../format.js";

const SERIES = [
  { key: "ok", label: "OK", color: "var(--good)" },
  { key: "needs_info", label: "Asked for more info", color: "var(--gray)" },
  { key: "blocked", label: "Blocked", color: "var(--warning)" },
  { key: "stopped", label: "Refused or rate limited", color: "var(--serious)" },
  { key: "failed", label: "Failed", color: "var(--critical)" },
];

const day = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
const tally = (object) => Object.entries(object).map(([k, v]) => `${words(k)} ${v}`).join(" · ") || "–";

export default function Overview({ data }) {
  const [asTable, setAsTable] = useState(false);
  const status = (k) => data.by_status[k] || 0;
  const plan = data.plans.full;
  const stepErrors = Object.entries(data.failed_steps);
  const planLabels = shortLabels(data.recent_plans.map((p) => p.started));
  const perDay = data.per_day.map((d) => ({ label: day(d.day), title: day(d.day), values: { ...d, stopped: d.refused + d.rate_limited } }));
  return (
    <>
      <div className="tiles">
        <Tile label="Requests" value={count(data.requests)} note={Object.keys(data.engines).length ? `engine: ${tally(data.engines)}` : ""} />
        <Tile label="Finished OK" value={count(status("ok"))} note={data.requests ? `${percent(status("ok") / data.requests)} of requests` : ""} />
        <Tile label="Asked for more info" value={count(status("needs_info"))} note="not an error" />
        <Tile label="Blocked or refused" value={count(status("blocked") + status("refused") + status("rate_limited"))} note={`blocked ${status("blocked")} · refused ${status("refused")} · rate limited ${status("rate_limited")}`} />
        <Tile label="Failed requests" value={count(data.failed_requests)} />
        <Tile label="Bookings (mock)" value={count(data.bookings)} />
      </div>

      <Card title="Time to make a full plan" note="Only plans that reached “awaiting approval” are timed. Median is the middle value; 9 in 10 finished within the p90 time.">
        {plan.count ? (
          <>
            <div className="tiles flat">
              <Tile label="Median" value={ms(plan.median_ms)} />
              <Tile label="p90" value={ms(plan.p90_ms)} />
              <Tile label="Slowest" value={ms(plan.max_ms)} />
              <Tile label="Plans timed" value={count(plan.count)} note={<Small n={plan.count} />} />
            </div>
            <h3>Last {data.recent_plans.length} full plans, oldest first</h3>
            <Columns
              data={data.recent_plans.map((p, i) => ({ label: planLabels[i], title: `${when(p.started)}${p.days ? ` · ${p.days} days` : ""}`, values: { time: p.duration_ms / 1000 } }))}
              series={[{ key: "time", label: "Time", color: "var(--series-1)" }]}
              format={(v) => `${Math.round(v * 10) / 10} s`}
              describe="Time taken by each recent full plan, in seconds"
            />
          </>
        ) : (
          <Empty>No full plan matches these filters yet.</Empty>
        )}
      </Card>

      <Card
        title="Requests per day"
        action={perDay.length > 0 && <button onClick={() => setAsTable(!asTable)}>{asTable ? "Show chart" : "Show as table"}</button>}
      >
        {!perDay.length ? (
          <Empty>Nothing recorded for these filters.</Empty>
        ) : asTable ? (
          <Table caption="Requests per day" rows={data.per_day} columns={[{ title: "Day", show: (d) => day(d.day) }, ...Object.entries(STATUSES).map(([k, label]) => ({ title: label, num: true, show: (d) => count(d[k]) }))]} />
        ) : (
          <>
            <Legend series={SERIES} />
            <Columns data={perDay} series={SERIES} describe="Requests per day by result" />
          </>
        )}
      </Card>

      <Card title="By type of request">
        <Table
          caption="By type of request"
          rows={data.by_kind}
          columns={[
            { title: "Type", show: (r) => KINDS[r.kind] || r.kind },
            { title: "Requests", num: true, show: (r) => <>{count(r.count)} <Small n={r.count} /></> },
            { title: "Results", show: (r) => Object.entries(r.statuses).map(([k, v]) => <span key={k} className="pair"><Status value={k} label={STATUSES[k]} /> {v}</span>) },
            { title: "Median", num: true, show: (r) => ms(r.median_ms) },
            { title: "p90", num: true, show: (r) => ms(r.p90_ms) },
            { title: "Slowest", num: true, show: (r) => ms(r.max_ms) },
          ]}
        />
      </Card>

      <div className="two">
        <Card title="Retries, replans and errors">
          <dl className="facts">
            <dt>Automatic replans (over budget or a failed check)</dt>
            <dd>{count(data.replans)}</dd>
            <dt>Plans changed at the traveller’s request</dt>
            <dd>{count(data.revisions)}</dd>
            <dt>Results of new plans</dt>
            <dd>{tally(data.plans.outcomes)}</dd>
            <dt>Steps that failed inside requests</dt>
            <dd>{stepErrors.length ? stepErrors.map(([k, v]) => `${STEP_TYPES[k] || k} ${v}`).join(" · ") : "none"}</dd>
          </dl>
          <p className="note">A failed step does not mean a failed plan: the planner retries or falls back. Agent retries are on the Agents tab.</p>
        </Card>

        <Card title="Today’s use of this app’s limits" note="Counted by this app for today. Your providers set their own limits; check their consoles.">
          {data.limits.length ? (
            <ul className="meters">
              {data.limits.map((l) => (
                <Meter key={l.name} label={l.label} used={l.used} limit={l.limit} />
              ))}
            </ul>
          ) : (
            <Empty>No AI, voice or live-price keys are set, so nothing is being counted.</Empty>
          )}
          <p className="note">Cost: the app is built to run on free tiers, so ₹0 is expected. It cannot see a provider’s bill.</p>
        </Card>
      </div>

      <Card title="Latest offline test scores" note={data.evals ? `From the last run of python evals/run_evals.py: ${data.evals.prompts ?? "?"} test requests, no AI keys needed, fixed date ${data.evals.fixed_date ?? "?"}. The report file was last changed ${when(data.evals.file_changed)}. These filters do not apply.` : ""}>
        {data.evals ? (
          <>
            <Table
              caption="Latest offline test scores"
              rows={data.evals.rows}
              columns={[
                { title: "Measure", show: (r) => r.metric },
                { title: "This planner", num: true, show: (r) => <b>{r.planner}</b> },
                { title: "Single-agent baseline", num: true, show: (r) => r.baseline },
                { title: "Applies to", show: (r) => r.applies },
              ]}
            />
            {data.evals.judge_mean != null && <p className="note">AI judge, preference match: {data.evals.judge_mean} out of 5 (AI judges are noisy).</p>}
          </>
        ) : (
          <Empty>No test report found. Run python evals/run_evals.py in the backend folder.</Empty>
        )}
      </Card>
    </>
  );
}
