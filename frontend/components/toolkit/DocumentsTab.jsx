// Travel document checklist, passport date check, reminders and the traveller's own document list.
// Only names and dates are ever stored: the server refuses document and card numbers.
import { useState } from "react";
import { api, toolPath } from "../../services/api.js";
import { download } from "../../services/download.js";
import { capitalise, longDay } from "../../services/format.js";
import Banner from "../common/Banner.jsx";
import { ExternalLink, LinkList } from "../common/Links.jsx";

const LEVELS = { required: ["Needed", "bad"], check: ["Check", "warn"], advised: ["Advised", ""] };
const note = { margin: "4px 0", fontSize: 13 };
const detail = { fontSize: 13 };

function Checklist({ data, thread, onChange }) {
  const tick = (id, done) => {
    if (data.can_save) onChange(toolPath(thread, "documents", "tick"), { check_id: id, done });
  };
  return (
    <>
      <h4>Checklist</h4>
      {data.checklist.map((item) => {
        const [label, colour] = LEVELS[item.level];
        return (
          <label className="checkline" key={item.id}>
            <input type="checkbox" className="tick" defaultChecked={item.done}
              onChange={(e) => tick(item.id, e.target.checked)} />
            <span>
              <b>{item.title}</b>{" "}
              <span className="badge" style={colour ? { color: `var(--${colour})` } : undefined}>{label}</span>
              <div className="muted" style={detail}>{item.detail} <ExternalLink link={item.link} /></div>
            </span>
          </label>
        );
      })}
      {!data.can_save && (
        <p className="muted" style={{ fontSize: 13 }}>
          Sign in to save your ticks and your documents. As a guest, ticks are lost when you leave this tab.
        </p>
      )}
    </>
  );
}

function PassportCheck({ thread }) {
  const [expiry, setExpiry] = useState("");
  const [issued, setIssued] = useState("");
  const [answer, setAnswer] = useState(null);

  const check = async () => {
    try {
      const result = await api(toolPath(thread, "documents", "passport-check"), { expiry, issued: issued || null });
      const kind = result.status === "problem" ? "bad" : result.status === "check" ? "warn" : "ok";
      setAnswer({ kind, messages: result.messages, links: result.links });
    } catch (e) {
      setAnswer({ kind: "bad", messages: [e.message], links: [] });
    }
  };

  return (
    <>
      <h4>Passport check</h4>
      <div className="row">
        <label className="field">Expiry date
          <input type="date" id="ppExpiry" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
        </label>
        <label className="field">Issue date (optional)
          <input type="date" id="ppIssued" value={issued} onChange={(e) => setIssued(e.target.value)} />
        </label>
        <button type="button" id="ppCheck" onClick={check}>Check</button>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: "4px 0" }}>Only the dates are used, and they are not saved.</p>
      <div id="ppOut">
        {answer && (
          <Banner kind={answer.kind}>
            {answer.messages.map((m, i) => <div key={i}>{m}</div>)}
            {answer.links.length > 0 && <div style={{ marginTop: 6 }}><LinkList links={answer.links} /></div>}
          </Banner>
        )}
      </div>
    </>
  );
}

function Reminders({ data }) {
  if (!data.reminders.length) {
    return <><h4>Reminders</h4><p className="muted">Nothing left to do for this trip.</p></>;
  }
  return (
    <>
      <h4>Reminders</h4>
      {data.reminders.map((r, i) => (
        <div className="place" key={i}>
          {r.problem ? "⚠️ " : ""}<b>{r.overdue && !r.problem ? "Do now" : longDay(r.date)}</b> · {r.title}
          {r.detail && <div className="muted" style={detail}>{r.detail}</div>}
        </div>
      ))}
      <div style={{ marginTop: 8 }}>
        <button type="button" id="icsBtn"
          onClick={() => download("trip-reminders.ics", data.calendar, "text/calendar;charset=utf-8")}>
          Add to my calendar (.ics file)
        </button>
      </div>
    </>
  );
}

function AddDocument({ kinds, thread, onChange }) {
  const [form, setForm] = useState({ kind: kinds[0], label: "", expiry: "", note: "" });
  const field = (key) => ({ value: form[key], onChange: (e) => setForm((f) => ({ ...f, [key]: e.target.value })) });
  const save = () => onChange(toolPath(thread, "documents"), { ...form, expiry: form.expiry || null });
  return (
    <div className="row" style={{ marginTop: 8, alignItems: "flex-end" }}>
      <label className="field">Type
        <select id="docKind" {...field("kind")}>
          {kinds.map((k) => <option key={k} value={k}>{capitalise(k.replace(/_/g, " "))}</option>)}
        </select>
      </label>
      <label className="field">Name<input id="docLabel" maxLength={80} placeholder="e.g. Passport - Asha" {...field("label")} /></label>
      <label className="field">Expiry (optional)<input type="date" id="docExpiry" {...field("expiry")} /></label>
      <label className="field">Note (optional)<input id="docNote" maxLength={200} {...field("note")} /></label>
      <button type="button" className="primary" id="docAdd" onClick={save}>Save</button>
    </div>
  );
}

export default function DocumentsTab({ data, thread, onChange, onSignIn }) {
  return (
    <>
      <p className="muted" style={{ margin: "6px 0", fontSize: 13 }}>{data.disclaimer}</p>
      <Checklist data={data} thread={thread} onChange={onChange} />
      <PassportCheck thread={thread} />
      <Reminders data={data} />
      <h4>My documents</h4>
      <p className="muted" style={note}>{data.number_warning}</p>
      {data.entries.map((entry) => (
        <div className="trip" key={entry.id}>
          <span>
            <b>{entry.label}</b> <span className="badge">{entry.kind.replace(/_/g, " ")}</span>
            {entry.expiry && <span className="muted"> · expires {longDay(entry.expiry)}</span>}
            {entry.note && <div className="muted" style={detail}>{entry.note}</div>}
          </span>
          <button type="button" data-del={entry.id} aria-label={`Delete ${entry.label}`}
            onClick={() => onChange(toolPath(thread, "documents", entry.id), null, "DELETE")}>Delete</button>
        </div>
      ))}
      {data.can_save
        ? <AddDocument kinds={data.kinds} thread={thread} onChange={onChange} />
        : <button type="button" id="docSignIn" onClick={onSignIn}>Sign in to save documents</button>}
    </>
  );
}
