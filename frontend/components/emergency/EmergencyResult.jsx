// Emergency numbers (tap to call), nearby hospitals, pharmacies and police, and official links.
import { longDay, safeUrl } from "../../services/format.js";
import Banner from "../common/Banner.jsx";
import { LinkList, PhoneLinks } from "../common/Links.jsx";

const PLACE_TITLES = { hospital: "🏥 Hospitals", clinic: "⚕️ Clinics", pharmacy: "💊 Pharmacies", police: "👮 Police" };
const small = { fontSize: 12, margin: "4px 0" };

function Numbers({ numbers }) {
  if (!numbers) return null;
  if (!numbers.verified) return <Banner kind="warn">{numbers.message}</Banner>;
  return (
    <>
      <div className="calls">
        {numbers.calls.map((call) => (
          <div className={`call ${call.primary ? "primary" : ""}`} key={call.label}>
            <div className="muted" style={{ fontSize: 13 }}>{call.label}</div>
            <PhoneLinks value={call.number} />
          </div>
        ))}
      </div>
      {numbers.note && <p className="muted" style={{ margin: "4px 0" }}>{numbers.note}</p>}
      <p className="muted" style={small}>Checked {longDay(numbers.checked_on)}. Sources: <LinkList links={numbers.sources} /></p>
    </>
  );
}

function Place({ place }) {
  const details = [place.address, place.open_24h ? "" : place.hours].filter(Boolean).join(" · ");
  return (
    <div className="place">
      <b>{place.name}</b> <span className="muted">· {String(place.distance_km)} km</span>
      {place.emergency_dept && <> <span className="badge live">emergency department listed</span></>}
      {place.open_24h && <> <span className="badge">open 24/7</span></>}
      <div style={{ fontSize: 14 }}>
        {place.phone && <>📞 <PhoneLinks value={place.phone} /> · </>}
        <a href={safeUrl(place.map_url)} target="_blank" rel="noopener noreferrer">Map</a>
      </div>
      {(place.address || (place.hours && !place.open_24h)) && (
        <div className="muted" style={{ fontSize: 13 }}>{details}</div>
      )}
    </div>
  );
}

function Nearby({ result }) {
  const nearby = result.nearby;
  if (!nearby) return null;
  if (!nearby.ok) return <Banner kind="warn">Nearby places could not be loaded. {nearby.reason}</Banner>;
  const groups = Object.keys(PLACE_TITLES).filter((kind) => nearby.places[kind]?.length);
  if (!groups.length) {
    return (
      <Banner kind="warn">
        OpenStreetMap lists no hospitals, pharmacies or police stations nearby. Call the emergency number.
      </Banner>
    );
  }
  return (
    <>
      <p className="muted" style={{ fontSize: 12, margin: "10px 0 0" }}>{result.map_note || ""}</p>
      {groups.map((kind) => (
        <div key={kind}>
          <h4>{PLACE_TITLES[kind]}</h4>
          {nearby.places[kind].map((place, i) => <Place key={i} place={place} />)}
        </div>
      ))}
    </>
  );
}

export default function EmergencyResult({ result }) {
  const where = result.where;
  return (
    <>
      <h4>
        Emergency numbers
        {where && where.source !== "device" ? ` · ${where.name}${where.country ? ", " + where.country : ""}` : ""}
      </h4>
      <Numbers numbers={result.numbers} />
      {where?.note && <p className="muted" style={{ fontSize: 12 }}>{where.note}</p>}
      <Nearby result={result} />
      <p style={{ fontSize: 14 }}><LinkList links={result.links} /></p>
    </>
  );
}
