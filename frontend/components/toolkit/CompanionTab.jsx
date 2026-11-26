// Packing list, useful facts, local customs and Wikivoyage notes.
import { useState } from "react";
import { safeUrl } from "../../services/format.js";
import { storage } from "../../services/storage.js";

const smallNote = { margin: "4px 0", fontSize: 13 };

function savedTicks(key) {
  try {
    return JSON.parse(storage.get(key) || "[]");
  } catch {
    return [];
  }
}

export default function CompanionTab({ data, thread }) {
  const storageKey = "tp_pack_" + thread;
  const [packed, setPacked] = useState(() => savedTicks(storageKey));
  const info = data.info;

  const tick = (id, on) => {
    const next = on ? [...packed, id] : packed.filter((x) => x !== id);
    setPacked(next);
    storage.set(storageKey, JSON.stringify(next));
  };

  return (
    <>
      {info && (
        <>
          <h4>Useful information · {data.destination}</h4>
          <div className="calls">
            {[["Money", info.currency], ["Traffic drives on the", info.drives_on], ["Plug types", info.plug_types],
              ["Dialling code", info.dialling_code]].map(([label, value]) => (
              <div className="call" key={label}>
                <div className="muted" style={{ fontSize: 13 }}>{label}</div><b>{value}</b>
              </div>
            ))}
          </div>
        </>
      )}
      <h4>Packing list</h4>
      {data.packing.note && <p className="muted" style={smallNote}>{data.packing.note}</p>}
      {data.packing.groups.map((group) => (
        <div style={{ marginTop: 8 }} key={group.title}>
          <b>{group.title}</b>
          {group.items.map((item) => {
            const id = group.title + "|" + item.name;
            return (
              <label className="checkline" key={id}>
                <input type="checkbox" className="pack" checked={packed.includes(id)}
                  onChange={(e) => tick(id, e.target.checked)} />
                <span>{item.name}{item.why && <span className="muted" style={{ fontSize: 13 }}> · {item.why}</span>}</span>
              </label>
            );
          })}
        </div>
      ))}
      <h4>Local customs</h4>
      {!data.customs.specific && (
        <p className="muted" style={smallNote}>General courtesy tips: there is no list for this country.</p>
      )}
      <ul>{data.customs.tips.map((t, i) => <li key={i}>{t}</li>)}</ul>
      {(data.local.sections || []).map((section, i) => (
        <div key={i}>
          <h4>
            {section.title}{" "}
            <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>
              from the <a href={safeUrl(section.url)} target="_blank" rel="noopener noreferrer">
                Wikivoyage guide to {section.page}</a> (CC BY-SA)
            </span>
          </h4>
          {section.text.map((paragraph, j) => <p className="muted" style={{ margin: "4px 0" }} key={j}>{paragraph}</p>)}
        </div>
      ))}
      <p className="muted" style={{ fontSize: 12 }}>{data.info_note} Ticks on the packing list are kept only in this browser.</p>
    </>
  );
}
