export default function GroupFit({ report }) {
  if (!report?.length) return null;
  return (
    <div className="card">
      <b>Group fit</b>
      {report.map((member) => (
        <div className="sight" key={member.name}>
          <b>{member.name}</b>{" "}
          <span className="muted">
            {member.likes.length ? "likes " + member.likes.join(", ") : "no interests given"}
            {member.avoid.length ? " · avoids " + member.avoid.join(", ") : ""}
          </span>
          <div className="when">
            {member.likes.length ? `${member.matched.length} of ${member.activities} planned activities match` : ""}
            {member.conflicts.length ? ` · includes something to avoid: ${member.conflicts.join(", ")}` : ""}
          </div>
        </div>
      ))}
    </div>
  );
}
