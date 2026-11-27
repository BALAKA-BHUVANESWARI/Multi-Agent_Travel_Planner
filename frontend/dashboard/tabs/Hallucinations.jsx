import { useState } from "react";
import { postJson } from "../api.js";
import { Card, Empty, Small, Status, Table, Tile } from "../charts.jsx";
import { KINDS, count, percent, when } from "../format.js";
import { FLAG_KINDS, JOBS, VERDICTS, named } from "../safetyWords.js";

const jobName = (job) => JOBS[job]?.[0] || job;
const kindList = (kinds) => Object.entries(kinds).map(([k, n]) => named(FLAG_KINDS, k).toLowerCase() + (n > 1 ? ` (${count(n)})` : "")).join(", ") || "–";
// the activity ranking is never shown as text, and request values are used by the planner, not displayed as an answer
const reached = (item) => {
  if (item.job === "ranking") return "Unknown ids were ignored";
  if (item.job === "request_reading") return "Given to the planner as part of your request";
  return item.shown ? "The traveller saw this text" : "Not shown to the traveller";
};

function Flagged({ item, detailed, onMark }) {
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
  return (
    <li className="flagged">
      <p className="flag-head">
        <a href={`#traces/${item.run_id}`}>{when(item.time)}</a>
        <b>{jobName(item.job)}</b>
        <span>{KINDS[item.request] || item.request}</span>
        <span>{item.provider}{item.model ? ` · ${item.model}` : ""}</span>
        <Status value={item.shown && (item.job === "chat" || item.job === "summary") ? "warning" : "info"} label={reached(item)} />
      </p>
      <p>
        {count(item.count)} {item.count === 1 ? "detail was" : "details were"} not found: {kindList(item.kinds)}
      </p>
      {item.has_text ? (
        <>
          {item.flags.length > 0 && (
            <ul className="examples">
              {item.flags.map((f, i) => (
                <li key={i}>
                  <span>{named(FLAG_KINDS, f.kind)}</span> <mark>{f.value}</mark>
                  {f.sentence && <q>{f.sentence}</q>}
                </li>
              ))}
            </ul>
          )}
          {item.ai_text && (
            <details>
              <summary>The whole AI text</summary>
              <pre>{item.ai_text}</pre>
            </details>
          )}
          <div className="verdict" role="group" aria-label={`Your judgement of the ${jobName(item.job)} from ${when(item.time)}`}>
            <span>Your judgement:</span>
            {Object.entries(VERDICTS).map(([key, label]) => (
              <button key={key} aria-pressed={item.verdict === key} disabled={busy} onClick={() => mark(item.verdict === key ? "" : key)}>
                {label}
              </button>
            ))}
            {!item.verdict && <small>not marked</small>}
          </div>
        </>
      ) : (
        // with basic records the note above the list already says why
        detailed && <p className="note">No examples were kept for this one, so it cannot be judged here.</p>
      )}
      {problem && <p className="problem" role="alert">{problem}</p>}
    </li>
  );
}

export default function Hallucinations({ data, show, onShow, onChanged }) {
  const sum = (key) => data.jobs.reduce((total, j) => total + j[key], 0);
  const judged = sum("real") + sum("false_alarm");
  const shownFlagged = data.jobs.filter((j) => j.job === "chat" || j.job === "summary").reduce((n, j) => n + j.flagged_and_shown, 0);
  const kinds = {};
  for (const job of data.jobs) {
    for (const [source, field] of [["looked_at", "looked"], ["kinds", "flagged"]]) {
      for (const [kind, n] of Object.entries(job[source])) {
        kinds[kind] = kinds[kind] || { kind, looked: 0, flagged: 0 };
        kinds[kind][field] += n;
      }
    }
  }
  const mark = async (id, verdict) => {
    await postJson("mark", { id, verdict });
    onChanged();
  };
  const detailed = data.recording.mode === "detailed";
  const corrected = sum("spelling_corrected");
  return (
    <>
      <p className="note">
        These are automatic checks, not proof. “Flagged” means a detail in what an AI returned was not found in the plan (or in your typed request). It can be a false alarm, and a made-up detail can also slip through. The checks only record and flag; they change nothing in the planner.
      </p>
      <div className="tiles">
        <Tile label="Checks run" value={count(data.checked)} note="one for each piece of AI output checked" />
        <Tile label="Flagged" value={count(data.flagged)} note={data.checked ? `${percent(data.flagged / data.checked)} of checks` : "nothing checked yet"} />
        <Tile label="Flagged AI text the traveller saw" value={count(shownFlagged)} note="summaries and chat answers" />
        <Tile label="Marked by you" value={count(judged)} note={judged ? `${count(sum("real"))} real, ${count(sum("false_alarm"))} false alarm` : "none yet"} />
      </div>
      {data.errors > 0 && <p className="problem">{count(data.errors)} check(s) could not run because of a fault in the check itself. Plans were not affected.</p>}
      {!data.checked && (
        <p className="note">Checks run only on AI output, so there is nothing here until an AI model writes a summary or a chat answer, reads part of a request, or ranks activities.</p>
      )}

      <Card title="By kind of AI output">
        <Table
          caption="By kind of AI output"
          rows={data.jobs}
          keyOf={(j) => j.job}
          columns={[
            { title: "AI output", show: (j) => <span className="wrapcell">{jobName(j.job)}</span> },
            { title: "Checked", num: true, show: (j) => <>{count(j.checked)} <Small n={j.checked} /></> },
            { title: "Flagged", num: true, show: (j) => (j.checked ? `${count(j.flagged)} (${percent(j.flagged_share)})` : "–") },
            { title: "Flagged and used or shown", num: true, show: (j) => (j.job === "ranking" ? "–" : count(j.flagged_and_shown)) },
            { title: "Real", num: true, show: (j) => count(j.real) },
            { title: "False alarm", num: true, show: (j) => count(j.false_alarm) },
            { title: "Not marked", num: true, show: (j) => count(j.unmarked) },
          ]}
        />
        {corrected > 0 && <p className="note">Also {count(corrected)} place name(s) where the AI corrected a one-letter spelling slip. These are not flagged.</p>}
      </Card>

      <div className="two">
        <Card title="By kind of detail">
          <Table
            caption="By kind of detail"
            rows={Object.values(kinds)}
            keyOf={(k) => k.kind}
            empty="Nothing has been compared yet."
            columns={[
              { title: "Detail", show: (k) => named(FLAG_KINDS, k.kind) },
              { title: "Compared", num: true, show: (k) => count(Math.max(k.looked, k.flagged)) },
              { title: "Not found", num: true, show: (k) => count(k.flagged) },
            ]}
          />
        </Card>
        <Card title="By AI model" note="“Saved answer” is an earlier answer used again without calling a model.">
          <Table
            caption="By AI model"
            rows={data.by_model}
            keyOf={(m) => `${m.provider}/${m.model}/${m.job}`}
            empty="No AI output has been checked."
            columns={[
              { title: "Provider and model", show: (m) => <span className="wrapcell">{m.model ? `${m.provider} · ${m.model}` : m.provider}</span> },
              { title: "AI output", show: (m) => jobName(m.job) },
              { title: "Checked", num: true, show: (m) => count(m.checked) },
              { title: "Flagged", num: true, show: (m) => count(m.flagged) },
            ]}
          />
        </Card>
      </div>

      <Card
        title="Flagged AI output"
        note={data.items_total > data.items.length ? `The newest ${data.items.length} of ${count(data.items_total)}.` : "Newest first."}
        action={
          <label className="check">
            Show
            <select value={show} onChange={(e) => onShow(e.target.value)}>
              <option value="">All flagged</option>
              <option value="unmarked">Not marked yet</option>
              <option value="real">Marked real</option>
              <option value="false_alarm">Marked false alarm</option>
            </select>
          </label>
        }
      >
        {!detailed && (
          <p className="note">
            To read what was flagged and judge it, add <code>RECORD_DETAILS=1</code> to <code>.env</code> and restart the server. Only requests made after that keep examples: the AI text and the flagged parts, with card and ID numbers removed, for {data.recording.detail_keep_days} days.
          </p>
        )}
        {data.items.length ? (
          <ul className="flag-list">
            {data.items.map((item) => (
              <Flagged key={item.id} item={item} detailed={detailed} onMark={mark} />
            ))}
          </ul>
        ) : (
          <Empty>{show ? "None with this choice." : "Nothing has been flagged for these filters."}</Empty>
        )}
      </Card>

      <Card title="What each check compares">
        <dl className="facts">
          {Object.entries(JOBS).map(([job, [name, what]]) => [<dt key={job + "t"}>{name}</dt>, <dd key={job + "d"}>{what}</dd>])}
        </dl>
        <h3>What the checks cannot see</h3>
        <ul className="limits">
          <li>Money is checked only when written with ₹, Rs, INR or “rupees”.</li>
          <li>A made-up place with a one-word name is noticed only if it is a known town or city. A real place the plan does not mention is flagged too.</li>
          <li>Weekday names, clock times, distances and opinions (“the best beach”) are not checked.</li>
          <li>A detail that matches the plan can still be used in a wrong sentence.</li>
          <li>An AI judge of answer quality is not part of these checks.</li>
        </ul>
      </Card>
    </>
  );
}
