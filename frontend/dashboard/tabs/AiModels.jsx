import { Card, Small, Status, Table } from "../charts.jsx";
import { KINDS, count, ms, when, words } from "../format.js";

const JOBS = { intake: "Reading the request", activities: "Ranking places", writer: "Writing the summary", chat: "Chat answers", voice: "Voice to text" };
const job = (name) => JOBS[name] || name;

export default function AiModels({ data }) {
  return (
    <>
      <Card title="By job" note="Each time the planner wanted help from an AI model. When no model answers, built-in rules do the job, so the plan is still made. “No key” means no AI key was set.">
        <Table
          caption="AI requests by job"
          rows={data.jobs}
          keyOf={(j) => j.job}
          empty="No AI help was requested in these requests."
          columns={[
            { title: "Job", show: (j) => job(j.job) },
            { title: "Asked", num: true, show: (j) => count(j.asked) },
            { title: "Answered by a model", num: true, show: (j) => count(j.answered) },
            { title: "…of those, by a backup", num: true, show: (j) => count(j.by_fallback) },
            { title: "From saved answers", num: true, show: (j) => count(j.from_cache) },
            { title: "No answer (rules used)", num: true, show: (j) => count(j.unanswered) },
            { title: "No key", num: true, show: (j) => count(j.no_key) },
          ]}
        />
      </Card>

      <Card title="By model" note="Every attempt sent to a provider. Token numbers come from the provider; when it sends none, they are estimated from the text length and marked.">
        <Table
          caption="AI calls by model"
          rows={data.models}
          empty="No call to an AI provider is recorded for these filters."
          columns={[
            { title: "Job", show: (m) => job(m.job) },
            { title: "Provider", show: (m) => m.provider },
            { title: "Model", show: (m) => m.model || "–" },
            { title: "Calls", num: true, show: (m) => <>{count(m.calls)} <Small n={m.calls} /></> },
            { title: "OK", num: true, show: (m) => count(m.ok) },
            { title: "Failed", num: true, show: (m) => <>{count(m.failed)}{m.failed > 0 && <small> {Object.entries(m.failures).map(([k, v]) => `${words(k)} ${v}`).join(", ")}</small>}</> },
            { title: "Retries", num: true, show: (m) => count(m.retries) },
            { title: "Backup answers", num: true, show: (m) => count(m.fallback_answers) },
            { title: "Median", num: true, show: (m) => ms(m.median_ms) },
            { title: "p90", num: true, show: (m) => ms(m.p90_ms) },
            { title: "Slowest", num: true, show: (m) => ms(m.max_ms) },
            { title: "Tokens in / out", num: true, show: (m) => (m.job === "voice" ? "–" : <>{count(m.tokens_in)} / {count(m.tokens_out)}{m.estimated_token_calls > 0 && <small> {m.estimated_token_calls} estimated</small>}</>) },
          ]}
        />
      </Card>

      <Card title="Each call" note={data.total_calls > data.calls.length ? `The newest ${data.calls.length} of ${count(data.total_calls)}. Download to get them all.` : "Newest first. Open a request to see where the call sits in it."}>
        <Table
          caption="Each AI call"
          rows={data.calls}
          empty="No AI call is recorded for these filters."
          columns={[
            { title: "Time", show: (c) => <a href={`#traces/${c.run_id}`}>{when(c.time)}</a> },
            { title: "Request", show: (c) => KINDS[c.request] || c.request },
            { title: "Job", show: (c) => job(c.job) },
            { title: "Provider", show: (c) => (c.provider === "cache" ? "saved answer" : c.provider === "none" ? "no model" : c.provider) },
            { title: "Model", show: (c) => c.model || "–" },
            { title: "Result", show: (c) => <Status value={c.result} /> },
            { title: "Why / code", show: (c) => [c.http_status && `HTTP ${c.http_status}`, words(c.error), c.fallback && "backup provider"].filter(Boolean).join(" · ") || "–" },
            { title: "Attempt", num: true, show: (c) => c.attempt ?? "–" },
            { title: "Time taken", num: true, show: (c) => ms(c.duration_ms) },
            { title: "Tokens in / out", num: true, show: (c) => (c.tokens_in == null ? "–" : `${count(c.tokens_in)} / ${count(c.tokens_out)}${c.tokens_estimated ? " (estimated)" : ""}`) },
          ]}
        />
      </Card>
    </>
  );
}
