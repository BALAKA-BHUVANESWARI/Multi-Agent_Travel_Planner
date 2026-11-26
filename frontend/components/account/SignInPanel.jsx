import { useState } from "react";
import { api } from "../../services/api.js";
import Panel from "./Panel.jsx";

export default function SignInPanel({ onSignedIn, onClose }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState(null);

  const send = async (path) => {
    try {
      const result = await api(path, { email, password });
      onSignedIn(result.token, result.user);
    } catch (e) {
      setMessage({ kind: "bad", text: e.message });
    }
  };

  return (
    <Panel title="Sign in or create an account" message={message} onClose={onClose}>
      <p className="muted" style={{ margin: "6px 0" }}>
        An account keeps your trips and remembers how you like to travel. It is stored only on this server.
      </p>
      <div className="row">
        <input id="email" type="email" placeholder="Email" autoComplete="username" value={email}
          onChange={(e) => setEmail(e.target.value)} />
        <input id="pw" type="password" placeholder="Password (8+ characters)" autoComplete="current-password"
          value={password} onChange={(e) => setPassword(e.target.value)} />
        <button className="primary" id="doLogin" onClick={() => send("/auth/login")}>Sign in</button>
        <button id="doRegister" onClick={() => send("/auth/register")}>Create account</button>
      </div>
    </Panel>
  );
}
