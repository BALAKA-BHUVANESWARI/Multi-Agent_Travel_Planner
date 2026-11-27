// "Explore more places": type any place name and the agents show it with its top sights and their pictures.
import { useState } from "react";
import { api } from "../../services/api.js";
import Icon from "../dashboard/Icon.jsx";
import ExploreResult from "./ExploreResult.jsx";

const EXAMPLES = ["Prague", "Hallstatt", "Hampi"];

export default function ExplorePlaces({ onPlan }) {
  const [name, setName] = useState("");
  const [state, setState] = useState({ busy: "", error: "", result: null });

  const search = async (text) => {
    const place = text.trim();
    if (!place || state.busy) return;
    setState({ busy: place, error: "", result: null });
    try {
      const result = await api("/explore", { place });
      setState({ busy: "", error: "", result });
    } catch (e) {
      // a failed fetch has no message a traveller can use
      const error = e instanceof TypeError ? "I couldn't reach the server. Check that it is running." : e.message;
      setState({ busy: "", error, result: null });
    }
  };
  const submit = (e) => {
    e.preventDefault();
    search(name);
  };

  return (
    <>
      <section className="card explore-card" id="explore">
        <h2><Icon name="search" />Explore more places</h2>
        <p className="muted">Type any city, town or place name. The agents will find it and show what to see there.</p>
        <form className="explore-form" onSubmit={submit}>
          <input id="exploreName" aria-label="Place name" maxLength={80} placeholder="e.g. Prague" value={name}
            onChange={(e) => setName(e.target.value)} />
          <button type="submit" className="primary" id="exploreGo" disabled={Boolean(state.busy) || !name.trim()}>
            {state.busy ? "Agents working…" : "Explore"}
          </button>
        </form>
        <div className="row chips">
          <span className="muted">Try:</span>
          {EXAMPLES.map((example) => (
            <button type="button" key={example} disabled={Boolean(state.busy)}
              onClick={() => { setName(example); search(example); }}>{example}</button>
          ))}
        </div>
      </section>
      <div aria-live="polite">
        {state.busy && (
          <p className="explore-note">Looking up {state.busy}. A new place can take up to a minute.</p>
        )}
        {state.error && <p className="explore-note bad" id="exploreError" role="alert">{state.error}</p>}
        {state.result && <ExploreResult result={state.result} onPlan={onPlan} />}
      </div>
    </>
  );
}
