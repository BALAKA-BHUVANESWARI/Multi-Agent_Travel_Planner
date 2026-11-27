import { Bars, Card, Empty, Small, Table } from "../charts.jsx";
import { count, ms, percent } from "../format.js";

export default function Agents({ data }) {
  const rows = data.agents;
  if (!rows.length) return <Card title="Agents"><Empty>No agent ran in the requests that match these filters.</Empty></Card>;
  return (
    <>
      <Card title="Typical time per agent" note="Median time of one run. The flight, hotel, weather and activities agents run side by side, so their times do not add up to the plan time.">
        <Bars rows={rows.map((a) => ({ key: a.agent, label: a.agent, value: a.median_ms, text: ms(a.median_ms) }))} />
      </Card>
      <Card
        title="Agents in detail"
        note="Success: the agent finished normally. Limited: it finished with less than asked, for example after a tool failed. Replans that did not need an agent are not counted. Retries are second and later attempts."
      >
        <Table
          caption="Agents in detail"
          rows={rows}
          keyOf={(a) => a.agent}
          columns={[
            { title: "Agent", show: (a) => a.agent },
            { title: "Runs", num: true, show: (a) => <>{count(a.runs)} <Small n={a.runs} /></> },
            { title: "Success rate", num: true, show: (a) => percent(a.success_rate) },
            { title: "Limited", num: true, show: (a) => count(a.degraded) },
            { title: "Errors", num: true, show: (a) => count(a.errors) },
            { title: "Median", num: true, show: (a) => ms(a.median_ms) },
            { title: "p90", num: true, show: (a) => ms(a.p90_ms) },
            { title: "Slowest", num: true, show: (a) => ms(a.max_ms) },
            { title: "Tool calls", num: true, show: (a) => count(a.tool_calls) },
            { title: "Tool retries", num: true, show: (a) => count(a.tool_retries) },
            { title: "Tool errors", num: true, show: (a) => count(a.tool_errors) },
            { title: "AI calls", num: true, show: (a) => count(a.ai_calls) },
            { title: "AI retries", num: true, show: (a) => count(a.ai_retries) },
            { title: "Lookups (failed)", num: true, show: (a) => `${count(a.lookups)} (${count(a.failed_lookups)})` },
          ]}
        />
      </Card>
    </>
  );
}
