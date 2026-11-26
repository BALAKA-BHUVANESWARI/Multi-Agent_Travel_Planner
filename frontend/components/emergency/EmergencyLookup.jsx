// Asks the server for emergency help. For a typed place or a trip the map search is a second step.
// Give it a new `key` for every new question.
import { useEffect, useState } from "react";
import { api } from "../../services/api.js";
import Banner from "../common/Banner.jsx";
import EmergencyResult from "./EmergencyResult.jsx";

export default function EmergencyLookup({ request }) {
  const [question, setQuestion] = useState(request);
  const [answer, setAnswer] = useState({ state: "looking" });

  useEffect(() => {
    let stale = false;
    setAnswer({ state: "looking" });
    api("/emergency", question)
      .then((result) => !stale && setAnswer({ state: "done", result }))
      .catch((e) => !stale && setAnswer({ state: "failed", error: e.message }));
    return () => {
      stale = true;
    };
  }, [question]);

  if (answer.state === "looking") return <p className="muted">Looking…</p>;
  if (answer.state === "failed") {
    return <Banner kind="bad">{answer.error} If this is urgent, call your local emergency number now.</Banner>;
  }
  const { result } = answer;
  return (
    <>
      <EmergencyResult result={result} />
      {!result.nearby && result.where.source !== "device" && (
        <button type="button" className="findNear" onClick={() => setQuestion({ ...question, nearby: true })}>
          Find hospitals and pharmacies nearby
        </button>
      )}
    </>
  );
}
