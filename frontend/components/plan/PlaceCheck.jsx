// "Did you mean ...?": asked when a typed or spoken name only matched a very small place.
export default function PlaceCheck({ check, onPick }) {
  const role = check.role === "origin" ? "Travelling from" : "Going to";
  return (
    <div className="card" role="group" aria-label={`${role}: which place did you mean?`}>
      <b>{role}: which place did you mean?</b>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="primary" data-place-check="suggested" onClick={() => onPick(check.suggested)}>
          {check.suggested_label}
        </button>
        <button data-place-check="typed" onClick={() => onPick(check.typed)}>{check.found_label}</button>
      </div>
      <p className="muted">Or correct the name in your request and plan again.</p>
    </div>
  );
}
