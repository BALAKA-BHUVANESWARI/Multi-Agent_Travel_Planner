// The box under the header that holds sign-in, "My trips" and "My preferences".
import Banner from "../common/Banner.jsx";

export default function Panel({ title, message, onClose, children }) {
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b>{title}</b>
        <button id="closePanel" onClick={onClose}>Close</button>
      </div>
      {children}
      <div id="panelMsg">{message && <Banner kind={message.kind}>{message.text}</Banner>}</div>
    </div>
  );
}
