import { useState } from "react";
import { postJson } from "../api.js";
import { Card, Empty, Status, Table, Tile } from "../charts.jsx";
import { count, percent, when, words } from "../format.js";

const GROUPS = { planning: "Planning requests", reading: "Dates and phrasings", chat: "Chat replies" };
const JOBS = { reading: "Request reading", ranking: "Activity ranking", summary: "Plan summary", chat: "Chat answer" };
const MEASURES = {
  outcome: "Expected result",
  constraints: "Request read correctly",
  budget: "Budget respected or warned",
  dates: "Valid dates",
  overlaps: "No overlaps",
  rain: "No outdoor plans in rain",
  prices: "Prices add up",
  schema: "Complete plan",
};
const LIVE_STATUS = { pass: ["ok", "No problem found"], fail: ["warning", "Problem found"], no_answer: ["failed", "No answer"], not_run: ["info", "Not run"], error: ["error", "The test failed"] };
const VOICE_STATUS = { pass: ["ok", "All right"], fail: ["warning", "Something read differently"], no_answer: ["failed", "Not transcribed"], not_recorded: ["info", "No recording"], not_run: ["info", "Not run"] };

const FIELD_WORDS = { right: "right", wrong: "wrong", missed: "missed", invented: "made up" };
const share = (part, whole) => (whole ? `${count(part)} of ${count(whole)}` : "–");
const passes = (g) => (g ? share(g.passed, g.total) : "–");
const version = (v) => (v ? <code>{v}</code> : "–");
const caseState = (c) => {
  if (c.known_gap) return c.passed ? ["warning", "Known gap, now passes"] : ["info", "Known gap"];
  return c.passed ? ["ok", "Passed"] : ["failed", "Failed"];
};
const State = ({ pair: [value, label] }) => <Status value={value} label={label} />;

function Choice({ label, value, onChange, choices }) {
  return (
    <label className="check">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {choices.map(([key, text]) => (
          <option key={key} value={key}>{text}</option>
        ))}
      </select>
    </label>
  );
}

// ---------------------------------------------------------------- offline tests
const CASE_SHOW = {
  attention: ["Failed and known gaps", (c) => !c.passed || c.known_gap],
  all: ["All cases", () => true],
  failed: ["Failed only", (c) => !c.passed && !c.known_gap],
  gaps: ["Known gaps", (c) => c.known_gap],
  baseline: ["Where the baseline failed", (c) => c.group === "planning" && !c.baseline_passed],
};

function Changes({ changes }) {
  if (!changes) return <p className="note">This is the only saved run, so there is nothing to compare it with yet.</p>;
  const { newly_failing: failing, newly_passing: passing, new_cases: added, removed_cases: removed } = changes;
  const parts = [];
  if (failing.length) parts.push(`now failing: ${failing.join(", ")}`);
  if (passing.length) parts.push(`now passing: ${passing.join(", ")}`);
  if (added) parts.push(`${count(added)} new cases`);
  if (removed) parts.push(`${count(removed)} cases removed`);
  return (
    <p className={failing.length ? "problem" : "note"}>
      Compared with the run of {when(changes.since)}: {parts.join("; ") || "no case changed between passed and failed"}.
    </p>
  );
}

function Offline({ offline }) {
  const [show, setShow] = useState("attention");
  const [group, setGroup] = useState("");
  const run = offline.latest;
  if (!run) {
    return (
      <Card title="Offline tests">
        <Empty>No saved run yet. In the backend folder, run <code>python evals/run_evals.py</code>, then press Refresh.</Empty>
      </Card>
    );
  }
  const gaps = run.cases.filter((c) => c.known_gap);
  const cases = run.cases.filter((c) => CASE_SHOW[show][1](c) && (!group || c.group === group));
  const measures = Object.keys(run.metrics.planner);
  const metric = (value) => (value?.share == null ? "–" : percent(value.share));
  return (
    <>
      <Card title="Offline tests: latest run" note={`${when(run.started)}${run.version ? `, code version ${run.version}` : ""}. Fixed date ${run.fixed_date}, no internet and no AI, so the same code gives the same result. The code version is the last commit; changes not committed yet do not show in it.`}>
        <div className="tiles flat">
          {Object.entries(GROUPS).map(([key, name]) => (
            <Tile key={key} label={`${name} passed`} value={passes(run.groups[key])} />
          ))}
          <Tile label="Known gaps" value={count(gaps.filter((c) => !c.passed).length)} note="not counted above" />
        </div>
        <Changes changes={offline.changes} />
      </Card>

      <Card title="This planner against a single-agent baseline" note="The baseline is one agent using the same tools one after another, without the safety check, weather swaps, budget retries, critic or approval step.">
        <Table
          caption="This planner against a single-agent baseline"
          rows={measures}
          keyOf={(m) => m}
          columns={[
            { title: "Measure", show: (m) => <span className="wrapcell">{MEASURES[m] || words(m)}</span> },
            { title: "This planner", num: true, show: (m) => <b>{metric(run.metrics.planner[m])}</b> },
            { title: "Baseline", num: true, show: (m) => metric(run.metrics.baseline[m]) },
            { title: "Cases", num: true, show: (m) => count(run.metrics.planner[m].cases) },
          ]}
        />
        {run.judge_mean != null && <p className="note">AI judge, preference match: {Math.round(run.judge_mean * 100) / 100} out of 5 (AI judges are noisy).</p>}
      </Card>

      <Card title="History" note={offline.kept > offline.history.length ? `The newest ${offline.history.length} of ${count(offline.kept)} saved runs.` : "Every saved run, newest first. The oldest are deleted after 100."}>
        <Table
          caption="History of offline test runs"
          rows={offline.history}
          keyOf={(r) => r.id}
          columns={[
            { title: "Run", show: (r) => when(r.started) },
            { title: "Code", show: (r) => version(r.version) },
            ...Object.entries(GROUPS).map(([key, name]) => ({ title: name, num: true, show: (r) => passes(r.groups?.[key]) })),
            { title: "Expected result: planner / baseline", num: true, show: (r) => `${percent(r.metrics.planner.outcome)} / ${percent(r.metrics.baseline.outcome)}` },
            { title: "Budget: planner / baseline", num: true, show: (r) => `${percent(r.metrics.planner.budget)} / ${percent(r.metrics.baseline.budget)}` },
          ]}
        />
      </Card>

      <Card
        title="Cases in the latest run"
        note={`${count(cases.length)} of ${count(run.cases.length)} cases shown. A known gap is something the planner is already known to get wrong.`}
        action={
          <span className="choices">
            <Choice label="Show" value={show} onChange={setShow} choices={Object.entries(CASE_SHOW).map(([k, [text]]) => [k, text])} />
            <Choice label="Group" value={group} onChange={setGroup} choices={[["", "All"], ...Object.entries(GROUPS)]} />
          </span>
        }
      >
        {cases.length ? (
          <ul className="flag-list">
            {cases.map((c) => (
              <li key={`${c.group}/${c.id}`} className="flagged">
                <p className="flag-head">
                  <State pair={caseState(c)} />
                  <b>{c.id}</b>
                  <span>{GROUPS[c.group]}</span>
                  {c.group === "planning" && <Status value={c.baseline_passed ? "ok" : "warning"} label={c.baseline_passed ? "Baseline passed" : "Baseline failed"} />}
                </p>
                <p><q>{c.text}</q></p>
                {c.known_gap && <p className="note">{c.known_gap}</p>}
                {c.failed.length > 0 && <p>{c.group === "planning" ? `Failed on: ${c.failed.map((m) => (MEASURES[m] || words(m)).toLowerCase()).join(", ")}` : c.failed.join("; ")}</p>}
                {c.group === "planning" && !c.baseline_passed && <p className="note">Baseline failed on: {c.baseline_failed.map((m) => (MEASURES[m] || words(m)).toLowerCase()).join(", ")}</p>}
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No case with this choice.</Empty>
        )}
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- live AI tests
function summaryRows(run) {
  const names = Object.keys(run.providers);
  const row = (label, group, show) => ({ label, cells: names.map((n) => (run.providers[n].groups[group]?.answered ? show(run.providers[n].groups[group]) : "–")) });
  const pct = (v) => (v == null ? "–" : percent(v));
  const noProblem = (g) => share(g.passed, g.answered);
  const judged = (g) => (g.judged ? `${share(g.judge_flagged, g.judged)}${g.judged_by_itself ? ` (${count(g.judged_by_itself)} judged by itself)` : ""}` : "not judged");
  const stars = (key) => (g) => (g[key] == null ? "not judged" : `${Math.round(g[key] * 10) / 10} of 5`);
  const total = (key) => names.map((n) => count(Object.values(run.providers[n].groups).reduce((sum, g) => sum + g[key], 0)));
  return {
    names,
    rows: [
      { label: "Model", cells: names.map((n) => run.providers[n].model || "–") },
      { label: "Calls used", cells: names.map((n) => count(run.providers[n].calls)) },
      row("Reading: details right with the rules alone", "reading", (g) => share(g.rules_right, g.fields)),
      row("Reading: details right with the AI added", "reading", (g) => share(g.ai_right, g.fields)),
      row("Reading: details made up", "reading", (g) => count(g.invented)),
      row(`Ranking: first 6 that match the preferences, rules`, "ranking", (g) => pct(g.rules_share)),
      row(`Ranking: first 6 that match the preferences, AI`, "ranking", (g) => pct(g.ai_share)),
      row("Ranking: AI judge, rules order", "ranking", stars("judge_rules")),
      row("Ranking: AI judge, AI order", "ranking", stars("judge_ai")),
      row("Ranking: ids made up", "ranking", (g) => count(g.unknown_ids)),
      row("Summaries with no problem found", "summary", noProblem),
      row("Summaries the app would not show", "summary", (g) => count(g.not_shown)),
      row("Chat answers the app would not show", "chat", (g) => (g.not_shown == null ? "–" : count(g.not_shown))),
      row("Summaries where the judge found unsupported statements", "summary", judged),
      row("Chat answers with no problem found", "chat", noProblem),
      row("Chat answers where the judge found unsupported statements", "chat", judged),
      { label: "Cases with no answer", cells: total("no_answer") },
      { label: "Calls that failed", cells: names.map((n) => { const c = run.providers[n].call_stats; return c ? share(c.failed, c.made) : "–"; }) },
      { label: "Typical reply time (successful calls)", cells: names.map((n) => { const s = run.providers[n].call_stats?.reply.median; return s == null ? "–" : `${Math.round(s * 10) / 10} s`; }) },
      { label: "Cases not run", cells: total("not_run") },
      { label: "Your checks", cells: names.map((n) => { const h = run.hand[n] || { good: 0, wrong: 0, answers: 0 }; return h.good + h.wrong ? `${count(h.good)} good, ${count(h.wrong)} wrong, of ${count(h.answers)} answers` : `none of ${count(h.answers)} answers`; }) },
    ],
  };
}

function judgeText(item) {
  const j = item.judge;
  if (!j) return null;
  if (j.not_run) return `AI judge not run: ${j.not_run}`;
  const who = j.itself ? `${j.by} (judging its own answer)` : j.by;
  if (item.group === "ranking") return `AI judge ${who}: rules order ${j.rules_score} of 5, AI order ${j.ai_score} of 5`;
  return j.unsupported.length ? `AI judge ${who} found no support for: ${j.unsupported.join(" · ")}` : `AI judge ${who} found nothing unsupported`;
}

function Answer({ item, onMark }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const mark = async (verdict) => {
    setBusy(true);
    setProblem("");
    try {
      await onMark(item.id, verdict);
    } catch (e) {
      setProblem(e.message);
    }
    setBusy(false);
  };
  const answered = item.status === "pass" || item.status === "fail";
  return (
    <li className="flagged">
      <p className="flag-head">
        <State pair={LIVE_STATUS[item.status] || ["info", item.status]} />
        <b>{item.provider}</b>
        <span>{JOBS[item.group]}</span>
        <span>{item.case}</span>
      </p>
      <p><q>{item.text}</q></p>
      {item.problems?.length > 0 && <ul className="limits">{item.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>}
      {answered && item.group === "ranking" && (
        <dl className="facts stacked">
          <dt>Order by the rules</dt>
          <dd>{item.rules_list.join(", ")}</dd>
          <dt>Order by the AI</dt>
          <dd>{item.ai_list.join(", ")}</dd>
        </dl>
      )}
      {answered && item.group === "reading" && (
        <Table
          caption={`How ${item.case} was read`}
          rows={Object.entries(item.fields)}
          keyOf={([k]) => k}
          columns={[
            { title: "Detail", show: ([k]) => words(k) },
            { title: "Correct", show: ([, f]) => String(f.expected ?? "nothing") },
            { title: "Rules alone", show: ([, f]) => String(f.rules ?? "–") },
            { title: "With AI", show: ([, f]) => <>{String(f.with_ai ?? "–")} <Status value={f.ai_result === "right" ? "ok" : "warning"} label={FIELD_WORDS[f.ai_result] || f.ai_result} />{f.ai_refused != null && <> (AI said {String(f.ai_refused)}; not used)</>}</> },
          ]}
        />
      )}
      {answered && (item.group === "summary" || item.group === "chat") && <p className="ai-answer">{item.answer}</p>}
      {judgeText(item) && <p className="note">{judgeText(item)}</p>}
      {answered && (
        <div className="verdict" role="group" aria-label={`Your check of ${item.provider} ${item.case}`}>
          <span>Your check:</span>
          {[["good", "Good"], ["wrong", "Wrong"]].map(([key, label]) => (
            <button key={key} aria-pressed={item.mark === key} disabled={busy} onClick={() => mark(item.mark === key ? "" : key)}>{label}</button>
          ))}
          {!item.mark && <small>not checked</small>}
        </div>
      )}
      {problem && <p className="problem" role="alert">{problem}</p>}
    </li>
  );
}

const PAGE = 10;                                            // answers listed before "Show more"
const LIVE_SHOW = {
  problems: ["Problems and no answer", (i) => i.status !== "pass"],
  unmarked: ["Not checked by you yet", (i) => !i.mark && (i.status === "pass" || i.status === "fail")],
  all: ["All", () => true],
};

function Live({ live, onPick, onChanged }) {
  const [show, setShow] = useState("all");
  const [job, setJob] = useState("");
  const [most, setMost] = useState(PAGE);
  const run = live.chosen;
  const how = (
    <>
      <p className="note">These call your AI providers with your keys, so you start them yourself from the backend folder. A run uses at most 100 calls, retries and the AI judge included, with the saved-answer cache off.</p>
      <pre>{"python evals/run_live_evals.py --list\npython evals/run_live_evals.py\npython evals/run_live_evals.py --report"}</pre>
    </>
  );
  if (!run) {
    return (
      <Card title="Live AI tests">
        {how}
        <Empty>No live test has been run yet.</Empty>
      </Card>
    );
  }
  const { names, rows } = summaryRows(run);
  const items = run.items.filter((i) => LIVE_SHOW[show][1](i) && (!job || i.group === job));
  const pick = (set) => (value) => {
    set(value);
    setMost(PAGE);
  };
  const mark = async (item, verdict) => {
    await postJson("mark", { eval_run: run.id, item, verdict });
    onChanged();
  };
  return (
    <>
      <Card
        title="Live AI tests"
        note={`Run of ${when(run.started)}: ${count(run.calls_used)} of ${count(run.limit)} calls used.${run.finished ? "" : " The run did not finish (stopped, or still going)."}`}
        action={live.runs.length > 1 && <Choice label="Run" value={run.id} onChange={onPick} choices={live.runs.map((r) => [r.id, when(r.started)])} />}
      >
        {how}
        {!run.measure && <p className="note">This run is from an older version of the test: a chat answer the app held back may show as “No answer”, and calls were not timed one by one.</p>}
        <Table
          caption="Live AI test results by provider"
          rows={rows}
          keyOf={(r) => r.label}
          columns={[
            { title: "Result", show: (r) => <span className="wrapcell">{r.label}</span> },
            ...names.map((name, i) => ({ title: name, num: true, show: (r) => <span className="wrapcell">{r.cells[i]}</span> })),
          ]}
        />
        <p className="note">These are small tests: a few cases for each job. “No problem found” means the automatic checks found nothing, not that the answer is good. The AI judge is also an AI and can be wrong. Read the answers below and mark them.</p>
      </Card>
      <Card
        title="Answers to check"
        note={`${count(Math.min(most, items.length))} shown of ${count(items.length)} with this choice, ${count(run.items.length)} in the run.`}
        action={
          <span className="choices">
            <Choice label="Show" value={show} onChange={pick(setShow)} choices={Object.entries(LIVE_SHOW).map(([k, [text]]) => [k, text])} />
            <Choice label="Job" value={job} onChange={pick(setJob)} choices={[["", "All"], ...Object.entries(JOBS)]} />
          </span>
        }
      >
        {items.length ? (
          <>
            <ul className="flag-list">{items.slice(0, most).map((item) => <Answer key={`${run.id}/${item.id}`} item={item} onMark={mark} />)}</ul>
            {items.length > most && <button onClick={() => setMost(most + PAGE)}>Show {count(Math.min(PAGE, items.length - most))} more</button>}
          </>
        ) : (
          <Empty>Nothing with this choice.</Empty>
        )}
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- voice test
function Voice({ voice }) {
  const run = voice.latest;
  return (
    <Card title="Voice test (optional)" note="You record about ten set sentences. This checks whether the planner reads the right places, numbers and dates from what the voice service heard. Only pass or fail is saved, never the sound or the words.">
      <pre>{"python evals/run_voice_test.py --list\npython evals/run_voice_test.py"}</pre>
      {!run ? (
        <Empty>No voice test has been run yet.</Empty>
      ) : (
        <>
          <p className="note">Latest run, {when(run.started)}: {share(run.summary.passed, run.summary.heard)} recordings read fully right.</p>
          <div className="tiles flat">
            {Object.entries(run.summary.groups).filter(([, g]) => g.checked).map(([name, g]) => (
              <Tile key={name} label={`${name[0].toUpperCase()}${name.slice(1)} right`} value={share(g.right, g.checked)} />
            ))}
          </div>
          <Table
            caption="Voice test by sentence"
            rows={run.items}
            keyOf={(i) => i.id}
            columns={[
              { title: "Sentence read out", show: (i) => <span className="wrapcell">{i.id}. {i.say}</span> },
              { title: "Result", show: (i) => <State pair={VOICE_STATUS[i.status] || ["info", i.status]} /> },
              { title: "Details", show: (i) => <span className="wrapcell">{i.problems.join("; ") || "–"}</span> },
            ]}
          />
        </>
      )}
    </Card>
  );
}

export default function Evaluations({ data, onPick, onChanged }) {
  return (
    <>
      <p className="note">These are tests with made-up requests, not your real trips, so the filters on the other tabs do not apply here. The dashboard only shows saved results; it never starts a test.</p>
      <Offline offline={data.offline} />
      <Live live={data.live} onPick={onPick} onChanged={onChanged} />
      <Voice voice={data.voice} />
    </>
  );
}
