// What the agents did, and what the run cost.
function runSummary(metrics) {
  const parts = [`${metrics.duration_s} s total`];
  const slowest = metrics.slowest_agent && metrics.agents[metrics.slowest_agent];
  if (slowest) parts.push(`slowest agent: ${metrics.slowest_agent} (${slowest.seconds.toFixed(1)} s)`);
  if (metrics.tool_calls !== undefined) {
    parts.push(`${metrics.tool_calls} tool calls` + (metrics.tool_failures ? ` (${metrics.tool_failures} failed)` : ""));
  }
  if (metrics.llm_calls !== undefined) {
    const extra = [];
    if (metrics.llm_tokens_est) extra.push(`~${metrics.llm_tokens_est} tokens est.`);
    if (metrics.llm_cache_hits) extra.push(`${metrics.llm_cache_hits} cached`);
    if (metrics.llm_fallbacks) extra.push(`${metrics.llm_fallbacks} fallbacks`);
    parts.push(`${metrics.llm_calls} LLM calls` + (extra.length ? ` (${extra.join(", ")})` : ""));
  }
  if (metrics.replans) parts.push(`${metrics.replans} automatic replans`);
  parts.push("cost $0 (free tiers)");
  return parts.join(" · ");
}

export default function AgentLog({ log = [], metrics }) {
  const lines = log.map((l) => `${l.t.slice(11, 23)}  ${l.agent.padEnd(10)} ${l.msg}`);
  return (
    <details className="card">
      <summary>Agent log ({log.length} events)</summary>
      {metrics && <p className="muted" style={{ margin: "8px 0 0", fontSize: 12 }}>Run: {runSummary(metrics)}</p>}
      <pre className="log">{lines.join("\n")}</pre>
    </details>
  );
}
