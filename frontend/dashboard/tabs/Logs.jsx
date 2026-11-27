import { Card, Status, Table } from "../charts.jsx";
import { KINDS, STEP_TYPES, count, ms, sourceName, when, words } from "../format.js";

const LEVELS = { error: "Errors", warning: "Warnings", info: "Normal" };

export default function Logs({ data, search, onSearch, onMore }) {
  const set = (name) => (event) => onSearch({ ...search, [name]: event.target.value });
  return (
    <Card title="Logs" note="Agent steps, AI calls, data lookups, safety checks, warnings and errors, newest first. The filters above also apply.">
      <div className="search" role="search">
        <label>
          Search
          <input type="search" value={search.q} onChange={set("q")} placeholder="for example openstreetmap, retry, blocked" maxLength={100} />
        </label>
        <label>
          Level
          <select value={search.level} onChange={set("level")}>
            <option value="">All</option>
            {Object.entries(LEVELS).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          Kind of entry
          <select value={search.type} onChange={set("type")}>
            <option value="">All</option>
            {[...new Set([...(data?.types || []), ...(search.type ? [search.type] : [])])].map((t) => (
              <option key={t} value={t}>{STEP_TYPES[t] || t}</option>
            ))}
          </select>
        </label>
      </div>
      {data && (
        <>
          <p className="note" role="status">
            {data.total > data.entries.length ? `Showing the newest ${count(data.entries.length)} of ${count(data.total)} entries.` : `${count(data.total)} entries.`}
          </p>
          <Table
            caption="Log entries"
            rows={data.entries}
            columns={[
              { title: "Time", show: (e) => <a href={`#traces/${e.run_id}`}>{when(e.time)}</a> },
              { title: "Level", show: (e) => <Status value={e.level} label={e.level === "info" ? "info" : e.level} /> },
              { title: "Kind", show: (e) => <>{STEP_TYPES[e.type] || e.type}<small> {KINDS[e.request] || e.request}</small></> },
              { title: "Name", show: (e) => (e.type.startsWith("retrieval") ? sourceName(e.name) : words(e.name)) },
              { title: "Status", show: (e) => words(e.status) },
              {
                title: "Details", wide: true,
                show: (e) => (
                  <>
                    {e.message || "–"}
                    {e.text && (
                      <details>
                        <summary>Kept text</summary>
                        <pre>{e.text}</pre>
                      </details>
                    )}
                  </>
                ),
              },
              { title: "Time taken", num: true, show: (e) => ms(e.duration_ms) },
            ]}
          />
          {data.total > data.entries.length && data.entries.length < 2000 && <button onClick={onMore}>Show more</button>}
        </>
      )}
    </Card>
  );
}
