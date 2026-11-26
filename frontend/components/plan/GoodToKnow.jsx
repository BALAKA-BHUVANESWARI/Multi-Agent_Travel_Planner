export default function GoodToKnow({ activities }) {
  const tips = activities.tips || [];
  const nearby = activities.nearby || [];
  if (!tips.length && !nearby.length) return null;
  return (
    <div className="card">
      <b>Good to know</b>
      {tips.map((tip, i) => <p className="muted" style={{ margin: "6px 0" }} key={i}>{tip.text}</p>)}
      {nearby.length > 0 && <p className="muted">Also nearby (no prices): {nearby.map((n) => n.name).join(", ")}</p>}
    </div>
  );
}
