// "Planning for a group?": one row per traveller with what they like and what they want to avoid.
import { INTERESTS, MAX_TRAVELLERS } from "../../services/constants.js";

const FIELDS = [
  ["name", "gName", 30, "Name"],
  ["likes", "gLikes", 100, "Likes, e.g. beaches, food"],
  ["avoid", "gAvoid", 100, "Wants to avoid, e.g. nightlife"],
];

export default function GroupEditor({ rows, onChange, onAdd, onRemove }) {
  return (
    <details id="groupBox" style={{ marginTop: 10 }}>
      <summary>Planning for a group? Tell me what each person likes</summary>
      <div id="members">
        {rows.map((row) => (
          <div className="member" key={row.id}>
            {FIELDS.map(([key, className, maxLength, placeholder]) => (
              <input key={key} className={className} maxLength={maxLength} placeholder={placeholder}
                aria-label={placeholder} value={row[key]} onChange={(e) => onChange(row.id, key, e.target.value)} />
            ))}
            <button type="button" onClick={() => onRemove(row.id)}>Remove</button>
          </div>
        ))}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button type="button" id="addMember" onClick={onAdd} disabled={rows.length >= MAX_TRAVELLERS}>Add a person</button>
        <span className="muted" style={{ fontSize: 13 }}>Interests: <span id="interestList">{INTERESTS.join(", ")}</span></span>
      </div>
    </details>
  );
}
