// Every price says whether it is live or an estimate, and where a live one came from.
export function PriceBadge({ block }) {
  return block?.live ? <span className="badge live">live</span> : <span className="badge">estimated</span>;
}

export function PriceSource({ block }) {
  if (!block?.live) return null;
  const fetched = new Date(block.fetched_at);
  const when = Number.isNaN(fetched.getTime()) ? "" :
    " · fetched " + fetched.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  return (
    <div className="muted" style={{ fontSize: 12 }}>
      {block.source || "web"}{when}{block.fx_note ? " · " + block.fx_note : ""}
    </div>
  );
}
