// "Plan your trip": a short form, or a request in your own words. Both send the planner a plain sentence.
import { useState } from "react";
import { INTERESTS, SAMPLE_REQUESTS } from "../../services/constants.js";
import { INDIA_DESTINATIONS } from "../../services/indiaDestinations.js";
import { checkTripForm, dateLimits, requestFromForm } from "../../services/tripText.js";
import Icon from "./Icon.jsx";

const shorten = (text) => (text.length > 46 ? text.slice(0, 46) + "…" : text);
const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i);

export default function PlanForm({ tab, onTab, form, onForm, text, onText, onPlan, onExplore, busy, children }) {
  const [problem, setProblem] = useState("");
  const set = (key) => (e) => {
    setProblem("");
    onForm({ ...form, [key]: e.target.value });
  };
  const toggle = (interest) => onForm({ ...form, interests: form.interests.includes(interest)
    ? form.interests.filter((x) => x !== interest) : [...form.interests, interest] });
  const limits = dateLimits(new Date());

  const submit = (e) => {
    e.preventDefault();
    if (busy) return;
    const wrong = checkTripForm(form, limits);
    setProblem(wrong);
    if (!wrong) onPlan(requestFromForm(form));
  };

  const tabButton = (value, label, icon) => (
    <button type="button" data-tab={value} aria-pressed={tab === value} onClick={() => onTab(value)}>
      <Icon name={icon} size={16} />{label}
    </button>
  );

  return (
    <section className="card plan-card" id="planForm">
      <span className="ribbon"><Icon name="plane" size={14} />Plan Your Trip</span>
      <div className="plan-tabs">
        {tabButton("form", "Trip details", "plane")}
        {tabButton("words", "Describe in your words", "bulb")}
        <button type="button" onClick={onExplore}><Icon name="globe" size={16} />Explore destinations</button>
      </div>

      <form className={tab === "form" ? "trip-form" : "hidden"} onSubmit={submit} noValidate>
        <label className="field">From
          <input id="fFrom" maxLength={60} placeholder="Your city, e.g. Mumbai" value={form.from} onChange={set("from")} />
        </label>
        <label className="field">To
          <input id="fTo" maxLength={60} list="toList" placeholder="Any place (empty = suggest)" value={form.to}
            onChange={set("to")} />
          <datalist id="toList">{INDIA_DESTINATIONS.map((d) => <option key={d.name} value={d.name} />)}</datalist>
        </label>
        <label className="field">Start date
          <input id="fDate" type="date" min={limits.min} max={limits.max} value={form.date} onChange={set("date")} />
        </label>
        <label className="field">Days
          <select id="fDays" value={form.days} onChange={set("days")}>
            {range(2, 14).map((n) => <option key={n} value={n}>{n} days</option>)}
          </select>
        </label>
        <label className="field">Travellers
          <select id="fTravellers" value={form.travellers} onChange={set("travellers")}>
            {range(1, 10).map((n) => <option key={n} value={n}>{n} {n === 1 ? "person" : "people"}</option>)}
          </select>
        </label>
        <label className="field">Total budget (₹)
          <input id="fBudget" inputMode="decimal" maxLength={14} placeholder="e.g. 60000 or 1.5 lakh"
            value={form.budget} onChange={set("budget")} />
        </label>
        <button type="submit" className="cta" id="goForm" disabled={busy}>
          {busy ? "Agents working…" : <>Plan My Trip <Icon name="arrow" /></>}
        </button>
        <div className="interests">
          <span className="muted">I like:</span>
          {INTERESTS.map((i) => (
            <button type="button" key={i} data-like={i} aria-pressed={form.interests.includes(i)}
              onClick={() => toggle(i)}>{i}</button>
          ))}
        </div>
        {problem && <p id="formError" role="alert">{problem}</p>}
      </form>

      <div className={tab === "words" ? "" : "hidden"}>
        <textarea id="prompt" maxLength={1000} value={text} onChange={(e) => onText(e.target.value)}
          aria-label="Describe your trip"
          placeholder="e.g. Plan a 5 day trip to Bangkok from Mumbai in January, budget 1.8 lakh for 2, love food and temples" />
        <div className="row" style={{ marginTop: 8 }}>
          <button className="primary" id="go" disabled={busy} onClick={() => text.trim() && onPlan(text.trim())}>
            Plan my trip
          </button>
          {busy && <span id="busy" className="muted">Agents working…</span>}
        </div>
        <div className="row chips" id="samples" style={{ marginTop: 10 }}>
          {SAMPLE_REQUESTS.map((sample) => (
            <button key={sample} title={sample} onClick={() => onText(sample)}>{shorten(sample)}</button>
          ))}
        </div>
      </div>
      {children}
    </section>
  );
}
