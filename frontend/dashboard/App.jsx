import { useCallback, useEffect, useState } from "react";
import { download, getJson, postJson, session, useData } from "./api.js";
import { KINDS, STATUSES, count, words } from "./format.js";
import Agents from "./tabs/Agents.jsx";
import AiModels from "./tabs/AiModels.jsx";
import Logs from "./tabs/Logs.jsx";
import Overview from "./tabs/Overview.jsx";
import Retrieval from "./tabs/Retrieval.jsx";
import { TraceDetail, TraceList } from "./tabs/Traces.jsx";

// id, name, what "Download" gives on this tab
const TABS = [
  ["overview", "Overview", "requests"],
  ["agents", "Agents", "agents"],
  ["ai", "AI models", "ai_calls"],
  ["traces", "Traces", "requests"],
  ["retrieval", "Retrieval", "lookups"],
  ["logs", "Logs", "logs"],
];
const DOWNLOADS = { requests: "requests", agents: "agent figures", ai_calls: "AI calls", lookups: "data lookups", logs: "log entries" };
const NO_FILTERS = { period: "all", date_from: "", date_to: "", kind: "", status: "", agent: "", model: "", run: "" };
const AUTO_SECONDS = 15;

const readRoute = () => {
  const [tab, id] = window.location.hash.replace(/^#/, "").split("/");
  const known = TABS.some(([key]) => key === tab) ? tab : "overview";
  return { tab: known, id: known === "traces" && /^[0-9a-f]{32}$/.test(id || "") ? id : "" };
};

function useRoute() {
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    const moved = () => {
      setRoute(readRoute());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", moved);
    return () => window.removeEventListener("hashchange", moved);
  }, []);
  return route;
}

function useDelayed(value, wait = 300) {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), wait);
    return () => clearTimeout(timer);
  }, [JSON.stringify(value), wait]); // eslint-disable-line react-hooks/exhaustive-deps
  return settled;
}

function Filters({ filters, options, onChange }) {
  const [runText, setRunText] = useState(filters.run);
  useEffect(() => setRunText(filters.run), [filters.run]);
  const pick = (name, label, choices) => (
    <label>
      {label}
      <select value={filters[name]} onChange={(e) => onChange({ ...filters, [name]: e.target.value })}>
        <option value="">All</option>
        {choices.map(([value, text]) => (
          <option key={value} value={value}>{text}</option>
        ))}
      </select>
    </label>
  );
  const date = (name, label) => (
    <label>
      {label}
      <input type="date" value={filters[name]} onChange={(e) => onChange({ ...filters, [name]: e.target.value })} />
    </label>
  );
  const dates = filters.period === "dates";
  const applyRun = () => onChange({ ...filters, run: /^[A-Za-z0-9_.:/+\-]{0,80}$/.test(runText.trim()) ? runText.trim() : "" });
  const changed = JSON.stringify(filters) !== JSON.stringify(NO_FILTERS);
  return (
    <form className="filters" aria-label="Filters" onSubmit={(e) => { e.preventDefault(); applyRun(); }}>
      <label>
        Period
        <select value={filters.period} onChange={(e) => onChange({ ...filters, period: e.target.value, date_from: "", date_to: "" })}>
          <option value="all">All kept records</option>
          <option value="today">Today</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
          <option value="dates">Choose dates</option>
        </select>
      </label>
      {dates && date("date_from", "From")}
      {dates && date("date_to", "To")}
      {pick("kind", "Request type", options.kinds.map((k) => [k, KINDS[k] || k]))}
      {pick("status", "Result", options.statuses.map((s) => [s, STATUSES[s] || words(s)]))}
      {pick("agent", "Agent", options.agents.map((a) => [a, a]))}
      {pick("model", "AI model", options.models.map((m) => [m, m]))}
      <label>
        Request or trip id
        <input value={runText} onChange={(e) => setRunText(e.target.value)} onBlur={applyRun} placeholder="any" maxLength={80} />
      </label>
      {changed && <button type="button" onClick={() => onChange(NO_FILTERS)}>Clear filters</button>}
    </form>
  );
}

function View({ route, filters, tick, logSearch, setLogSearch }) {
  const [logLimit, setLogLimit] = useState(200);
  const typed = useDelayed(logSearch);
  const params = filters.period === "dates" ? { ...filters, period: "all" } : filters;
  const detail = route.tab === "traces" && route.id;
  const path = detail ? `runs/${route.id}` : route.tab === "traces" ? "runs" : route.tab;
  const { data, error, loading } = useData(path, detail ? {} : route.tab === "logs" ? { ...params, ...typed, limit: logLimit } : params, tick);
  const problem = error && <p className="problem" role="alert">{error}</p>;
  if (!data) return problem || <p className="empty" role="status">Loading…</p>;
  const narrowed = !detail && filters.agent && <p className="note">With an agent chosen: requests where it ran, and only its own steps and the calls made inside them.</p>;
  let body;
  if (detail) body = <TraceDetail key={route.id} data={data} />;
  else if (route.tab === "overview") body = <Overview data={data} />;
  else if (route.tab === "agents") body = <Agents data={data} />;
  else if (route.tab === "ai") body = <AiModels data={data} />;
  else if (route.tab === "traces") body = <TraceList data={data} />;
  else if (route.tab === "retrieval") body = <Retrieval data={data} />;
  else body = <Logs data={data} search={logSearch} onSearch={setLogSearch} onMore={() => setLogLimit(logLimit + 400)} />;
  return (
    <div className={loading ? "stale" : undefined} aria-busy={loading}>
      {problem}
      {narrowed}
      {body}
    </div>
  );
}

function Dashboard({ onSignOut }) {
  const route = useRoute();
  const [filters, setFilters] = useState(NO_FILTERS);
  const [logSearch, setLogSearch] = useState({ q: "", level: "", type: "" });
  const [tick, setTick] = useState(0);
  const [auto, setAuto] = useState(false);
  const [updated, setUpdated] = useState(() => new Date());
  const [saveProblem, setSaveProblem] = useState("");
  const options = useData("options", {}, tick);
  const refresh = useCallback(() => {
    setTick((t) => t + 1);
    setUpdated(new Date());
  }, []);
  useEffect(() => {
    if (!auto) return undefined;
    const timer = setInterval(() => !document.hidden && refresh(), AUTO_SECONDS * 1000);
    return () => clearInterval(timer);
  }, [auto, refresh]);

  const what = TABS.find(([key]) => key === route.tab)[2];
  const save = async (format) => {
    setSaveProblem("");
    const params = filters.period === "dates" ? { ...filters, period: "all" } : filters;
    try {
      await download({ ...params, ...(route.tab === "logs" ? logSearch : {}), what, format });
    } catch (e) {
      setSaveProblem(e.message);
    }
  };
  const record = options.data?.recording;
  const detail = route.tab === "traces" && route.id;

  return (
    <div className="board">
      <aside>
        <div className="brand">
          <b>ExecuTrip</b>
          <span>Metrics dashboard</span>
        </div>
        <nav aria-label="Dashboard sections">
          {TABS.map(([key, name]) => (
            <a key={key} href={`#${key}`} aria-current={route.tab === key ? "page" : undefined}>{name}</a>
          ))}
        </nav>
        <div className="aside-foot">
          <a href="/">Open the planner</a>
          <button onClick={onSignOut}>Sign out</button>
        </div>
      </aside>
      <main>
        <header className="top">
          <h1>{TABS.find(([key]) => key === route.tab)[1]}</h1>
          <div className="actions">
            <span className="note">Updated {updated.toLocaleTimeString("en-GB")}</span>
            <label className="check">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              Auto-refresh every {AUTO_SECONDS} s
            </label>
            <button onClick={refresh}>Refresh</button>
            {!detail && (
              <span className="downloads">
                Download {DOWNLOADS[what]}:
                <button onClick={() => save("csv")}>CSV</button>
                <button onClick={() => save("json")}>JSON</button>
              </span>
            )}
          </div>
        </header>
        {saveProblem && <p className="problem" role="alert">{saveProblem}</p>}
        {record && (
          <p className="banner">
            {record.mode === "off"
              ? "Recording is switched off (OBSERVABILITY=0). You are seeing what was recorded earlier."
              : record.mode === "detailed"
                ? `Detailed recording is on: cleaned request and AI text is kept for ${record.detail_keep_days} days, other records for ${record.keep_days} days.`
                : `Basic recording: names, times, counts and result codes, kept for ${record.keep_days} days. No typed text or AI answers.`}
            {record.write_errors > 0 && ` ${count(record.write_errors)} records could not be saved since the server started.`}
            {options.data.recorded === 0 && " Nothing is recorded yet: make a plan in the planner, then press Refresh."}
          </p>
        )}
        {!detail && options.data && <Filters filters={filters} options={options.data} onChange={setFilters} />}
        <View key={route.tab} route={route} filters={filters} tick={tick} logSearch={logSearch} setLogSearch={setLogSearch} />
      </main>
    </div>
  );
}

function SignIn({ onDone, message }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const out = await postJson("login", { password });
      session.set(out.token);
      onDone();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };
  return (
    <form className="gate" onSubmit={submit}>
      <h1>Metrics dashboard</h1>
      <p>Type the dashboard password from your <code>.env</code> file.</p>
      {message && !error && <p className="note">{message}</p>}
      <label>
        Password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus required maxLength={200} />
      </label>
      {error && <p className="problem" role="alert">{error}</p>}
      <button className="primary" disabled={busy || !password}>Sign in</button>
      <a href="/">Back to the planner</a>
    </form>
  );
}

function Off({ status, onRetry }) {
  const why = {
    off: "It has not been switched on.",
    no_password: "It is switched on, but no password is set.",
    password_too_short: `The password must be at least ${status.min_password} characters.`,
  }[status.reason];
  return (
    <div className="gate wide">
      <h1>The dashboard is off</h1>
      <p>{why}</p>
      <p>To use it, add these two lines to the <code>.env</code> file in the project folder, with a password of your own (at least {status.min_password} characters):</p>
      <pre>{"DASHBOARD=1\nDASHBOARD_PASSWORD=choose-your-own-password"}</pre>
      <p>Then stop the server, start it again and press the button.</p>
      <button className="primary" onClick={onRetry}>Check again</button>
      <a href="/">Back to the planner</a>
    </div>
  );
}

export default function App() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [signedIn, setSignedIn] = useState(Boolean(session.token));
  const [message, setMessage] = useState("");
  const check = useCallback(() => {
    setError("");
    getJson("status").then(setStatus, (e) => setError(e.message));
  }, []);
  useEffect(() => {
    session.onSignedOut(() => {
      setMessage("You were signed out: the sign-in ran out or the server was restarted.");
      setSignedIn(false);
    });
    check();
  }, [check]);

  const signOut = async () => {
    await postJson("logout", {}).catch(() => {});
    session.set("");
    setMessage("");
    setSignedIn(false);
  };

  if (error) return <div className="gate"><p className="problem" role="alert">{error}</p><button onClick={check}>Try again</button></div>;
  if (!status) return <p className="gate" role="status">Loading…</p>;
  if (!status.enabled) return <Off status={status} onRetry={check} />;
  if (!signedIn) return <SignIn message={message} onDone={() => setSignedIn(true)} />;
  return <Dashboard onSignOut={signOut} />;
}
