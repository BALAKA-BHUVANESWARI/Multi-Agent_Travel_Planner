import AccountBar from "../account/AccountBar.jsx";

export default function Header({ onToggleEmergency, ...account }) {
  return (
    <>
      <div className="topbar">
        <h1>AI Multi-Agent Travel Planner</h1>
        <div className="row">
          <button type="button" className="sos" id="sosBtn" onClick={onToggleEmergency}>🆘 Emergency help</button>
          <AccountBar {...account} />
        </div>
      </div>
      <p className="sub">
        Describe a trip to <b>any city or town</b> in plain language. Agents plan travel, hotel, weather and activities
        in parallel; you approve before anything is (mock) booked.
      </p>
    </>
  );
}
