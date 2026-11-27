import { Bars, Card, Empty, Small, Status, Table, Tile } from "../charts.jsx";
import { PLAN_SOURCES, count, ms, percent, sourceName, when, words } from "../format.js";

export default function Retrieval({ data }) {
  const used = data.in_plans;
  const parts = Object.entries(used.by_source).sort((a, b) => b[1] - a[1]);
  const price = (key) => Object.entries(data.prices[key]).map(([k, v]) => `${words(k)} ${v}`).join(" · ") || "–";
  return (
    <>
      <div className="tiles">
        <Tile label="Data lookups" value={count(data.total_lookups)} />
        <Tile label="Real places in finished plans" value={percent(used.real_share)} note={used.activities ? `${count(used.activities - (used.by_source.generic || 0))} of ${count(used.activities)} activities in ${count(used.plans)} plan versions` : "no finished plan yet"} />
        <Tile label="Transport prices" value={price("transport_price")} note="per plan version" />
        <Tile label="Hotel prices" value={price("hotel_price")} note="per plan version" />
      </div>

      <Card title="Where the activities in finished plans came from" note="Counted from each finished plan and each changed version of it. “Generic filler” is a suggestion that names no real place.">
        {parts.length ? (
          <Bars rows={parts.map(([k, v]) => ({ key: k, label: PLAN_SOURCES[k] || k, value: v, text: `${count(v)} (${percent(v / used.activities)})`, color: k === "generic" ? "var(--gray)" : undefined }))} />
        ) : (
          <Empty>No finished plan matches these filters.</Empty>
        )}
      </Card>

      <Card title="Each source" note="“Found nothing” means the source answered with no result, which is different from failing. “Skipped” means it was not asked, for example just after it had failed. “From cache” answers were saved earlier and used no internet.">
        <Table
          caption="Each source"
          rows={data.sources}
          keyOf={(s) => s.source}
          empty="No lookup is recorded for these filters."
          columns={[
            { title: "Source", show: (s) => sourceName(s.source) },
            { title: "Lookups", num: true, show: (s) => <>{count(s.lookups)} <Small n={s.lookups} /></> },
            { title: "Found", num: true, show: (s) => count(s.ok) },
            { title: "Found nothing", num: true, show: (s) => count(s.empty) },
            { title: "Failed", num: true, show: (s) => count(s.error) },
            { title: "Timed out", num: true, show: (s) => count(s.timeout) },
            { title: "Skipped", num: true, show: (s) => count(s.skipped) },
            { title: "From cache", num: true, show: (s) => count(s.from_cache) },
            { title: "Results each", num: true, show: (s) => s.results_per_lookup ?? "–" },
            { title: "Median", num: true, show: (s) => ms(s.median_ms) },
            { title: "p90", num: true, show: (s) => ms(s.p90_ms) },
            { title: "Slowest", num: true, show: (s) => ms(s.max_ms) },
          ]}
        />
      </Card>

      <div className="two">
        <Card title="Fallbacks used" note="Another source or an estimate was used instead.">
          <Table caption="Fallbacks used" rows={data.fallbacks} empty="None." columns={[{ title: "What happened", show: (f) => sourceName(f.what) }, { title: "Times", num: true, show: (f) => count(f.times) }]} />
        </Card>
        <Card title="Plan stopped waiting" note="The plan went on without a slow source. Its own lookup may still finish afterwards.">
          <Table caption="Plan stopped waiting" rows={data.gave_up} empty="Never." columns={[{ title: "Waiting for", show: (f) => sourceName(f.what) }, { title: "Times", num: true, show: (f) => count(f.times) }]} />
        </Card>
      </div>

      <Card title="Latest failures and timeouts">
        <Table
          caption="Latest failures and timeouts"
          rows={data.problems}
          empty="No failed or timed-out lookup for these filters."
          columns={[
            { title: "Time", show: (p) => <a href={`#traces/${p.run_id}`}>{when(p.time)}</a> },
            { title: "Source", show: (p) => sourceName(p.source) },
            { title: "Result", show: (p) => <Status value={p.status} /> },
            { title: "Why / code", show: (p) => [p.http_status && `HTTP ${p.http_status}`, words(p.error)].filter(Boolean).join(" · ") || "–" },
            { title: "Time taken", num: true, show: (p) => ms(p.duration_ms) },
          ]}
        />
      </Card>
    </>
  );
}
