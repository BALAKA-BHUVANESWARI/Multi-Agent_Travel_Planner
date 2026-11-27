import { Bars, Card, Empty, Status, Table, Tile } from "../charts.jsx";
import { KINDS, count, percent, when, words } from "../format.js";
import { AI_CHECKS, INPUT_REASONS, PLAN_CODES, RATE_BUCKETS, RULES, CHAT_TOPICS, CHANGE_KINDS, named } from "../safetyWords.js";

// {code: times} -> rows for a small table, most frequent first
const rows = (tally, names) =>
  Object.entries(tally || {})
    .sort((a, b) => b[1] - a[1])
    .map(([code, times]) => ({ code, label: named(names, code), times }));

function Counts({ caption, first, data, names, empty }) {
  return (
    <Table
      caption={caption}
      rows={rows(data, names)}
      keyOf={(r) => r.code}
      empty={empty}
      columns={[
        { title: first, show: (r) => <span className="wrapcell">{r.label}</span> },
        { title: "Times", num: true, show: (r) => count(r.times) },
      ]}
    />
  );
}

export default function Guardrails({ data }) {
  const { inputs, plan_checks: plans, changes, web_text: web } = data;
  const rejected = data.ai_output.reduce((sum, r) => sum + r.rejected, 0);
  const spoken = data.private.spoken;
  const kinds = [...new Set([...Object.keys(data.private.typed), ...Object.keys(spoken)])];
  const limits = [
    ...(changes.limit_reached ? [{ code: "limit", label: "Change limit reached", times: changes.limit_reached }] : []),
    ...rows(changes.not_possible, CHANGE_KINDS).map((r) => ({ ...r, code: `no-${r.code}`, label: `Change not possible: ${r.label}` })),
    ...(changes.not_understood ? [{ code: "unclear", label: "Change request not understood", times: changes.not_understood }] : []),
    ...rows(data.rate_limits, RATE_BUCKETS).map((r) => ({ ...r, code: `rate-${r.code}` })),
    ...(data.place_questions ? [{ code: "place", label: "Asked “did you mean …?” about a place", times: data.place_questions }] : []),
  ];
  return (
    <>
      <p className="note">
        Rules that run in code and decide what is allowed. A rule acting does not mean someone attacked the planner: an ordinary request can be stopped by mistake. Emergency help and trip toolkit requests are never recorded, and wrong dashboard passwords are not counted. Limits show only for requests that are recorded.
      </p>
      <div className="tiles">
        <Tile label="Times a rule stepped in" value={count(data.acted)} note="stopped, removed, rejected or asked first" />
        <Tile label="Typed messages stopped" value={count(inputs.blocked)} note={inputs.checked ? `of ${count(inputs.checked)} input checks (${percent(inputs.blocked / inputs.checked)})` : "no input checked yet"} />
        <Tile label="AI output thrown away" value={count(rejected)} note="the planner’s own rules took over" />
        <Tile label="Plan checks that sent a plan back" value={count(plans.blocking)} note={`of ${count(plans.checked)} plan checks`} />
      </div>

      <div className="two">
        <Card title="Why typed messages were stopped">
          <Counts caption="Why typed messages were stopped" first="Reason" data={inputs.by_reason} names={INPUT_REASONS} empty="No message was stopped." />
        </Card>
        <Card title="Private details withheld" note="Only the type is recorded, never the number or password itself.">
          <Table
            caption="Private details withheld"
            rows={kinds}
            keyOf={(k) => k}
            empty="None found."
            columns={[
              { title: "Type", show: (k) => words(k) },
              { title: "Typed", num: true, show: (k) => count(data.private.typed[k] || 0) },
              { title: "Spoken", num: true, show: (k) => count(spoken[k] || 0) },
            ]}
          />
        </Card>
      </div>

      <Card title="AI output the rules threw away" note="What an AI model returns is used only after these checks. “Checked” counts each time the rule ran.">
        <Table
          caption="AI output the rules threw away"
          rows={data.ai_output}
          keyOf={(r) => r.check}
          columns={[
            { title: "Check", show: (r) => <span className="wrapcell">{AI_CHECKS[r.check]?.[0] || words(r.check)}</span> },
            { title: "Checked", num: true, show: (r) => count(r.checked) },
            { title: "Thrown away", num: true, show: (r) => count(r.rejected) },
            { title: "What happens instead", wide: true, show: (r) => AI_CHECKS[r.check]?.[1] || "–" },
          ]}
        />
      </Card>

      <Card
        title="Plan checks"
        note={`The finished draft is checked for dates, overlaps, hotel nights, the budget, and that every price comes from a tool and the totals add up. A blocking problem sends the plan back to be redone. Price or total failures: ${count(plans.price_failures)}.`}
      >
        <p>
          {count(plans.checked)} checks: {count(plans.passed)} passed, {count(plans.warnings_only)} with notes only, {count(plans.blocking)} with a blocking problem.
        </p>
        {Object.keys(plans.codes).length ? (
          <>
            <h3>Problems found (one check can find several)</h3>
            <Bars rows={rows(plans.codes, PLAN_CODES).map((r) => ({ key: r.code, label: r.label, value: r.times, text: count(r.times) }))} />
          </>
        ) : (
          <Empty>No problem was found by the plan checks.</Empty>
        )}
      </Card>

      <div className="two">
        <Card title="Limits and questions back">
          <Table
            caption="Limits and questions back"
            rows={limits}
            keyOf={(r) => r.code}
            empty="No limit was reached."
            columns={[
              { title: "What happened", show: (r) => <span className="wrapcell">{r.label}</span> },
              { title: "Times", num: true, show: (r) => count(r.times) },
            ]}
          />
        </Card>
        <Card title="Chat replies fixed in advance" note="These topics are answered by a set reply before any AI model sees them.">
          <Counts caption="Chat replies fixed in advance" first="Topic" data={data.chat_replies} names={CHAT_TOPICS} empty="No such question in chat." />
        </Card>
      </div>

      <Card title="Text from the web">
        <p>
          {web.times
            ? `Instruction-like phrases were removed ${count(web.phrases)} time(s) while cleaning web or AI text, in ${count(web.times)} cleaning step(s). The same saved text can be cleaned again, so this counts times, not different texts.`
            : "No instruction-like phrase has been found in text from the web."}
        </p>
      </Card>

      <Card title="Latest times a rule stepped in" note={data.acted > data.recent.length ? `The newest ${data.recent.length} of ${count(data.acted)}. Download to get them all.` : "Newest first. Open a request to see where the rule ran."}>
        <Table
          caption="Latest times a rule stepped in"
          rows={data.recent}
          keyOf={(e) => e.id}
          empty="No rule has stepped in for these filters."
          columns={[
            { title: "Time", show: (e) => <a href={`#traces/${e.run_id}`}>{when(e.time)}</a> },
            { title: "Request", show: (e) => KINDS[e.request] || e.request },
            { title: "Rule", show: (e) => RULES[e.check] || words(e.check) },
            { title: "Result", show: (e) => <Status value={e.status} /> },
            { title: "Reason", wide: true, show: (e) => <>{reason(e)}{e.text && <small className="saved">{e.text}</small>}</> },
          ]}
        />
      </Card>
    </>
  );
}

const REASONS = { input_check: INPUT_REASONS, feedback_check: INPUT_REASONS, chat_fixed_reply: CHAT_TOPICS, rate_limit: RATE_BUCKETS, change_not_possible: CHANGE_KINDS };

function reason(e) {
  if (e.check === "critic_checks") return e.what.split(", ").map((code) => named(PLAN_CODES, code)).join(", ") || "–";
  return e.what ? named(REASONS[e.check], e.what) : "–";
}
