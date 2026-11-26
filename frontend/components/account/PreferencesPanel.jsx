import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "../../services/api.js";
import { INTERESTS } from "../../services/constants.js";
import { capitalise } from "../../services/format.js";
import Banner from "../common/Banner.jsx";
import Panel from "./Panel.jsx";

const toForm = (memory) => ({
  home_city: memory.home_city || "",
  travel_mode: memory.travel_mode || "",
  pace: memory.pace || "",
  preferences: memory.preferences || [],
  remember: memory.remember !== false,
});

const choices = (values) =>
  values.map((v) => <option key={v} value={v}>{v ? capitalise(v) : "Not set"}</option>);

export default function PreferencesPanel({ onDeleted, onClose }) {
  const [form, setForm] = useState(null);
  const [message, setMessage] = useState(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const fail = (e) => setMessage({ kind: "bad", text: e.message });

  const load = useCallback(async () => {
    try {
      const { memory } = await api("/me");
      setForm(toForm(memory));
    } catch (e) {
      fail(e);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const toggle = (interest, on) =>
    set("preferences", on ? [...form.preferences, interest] : form.preferences.filter((x) => x !== interest));

  const save = async () => {
    try {
      await api("/me/memory", { ...form, preferences: INTERESTS.filter((i) => form.preferences.includes(i)) }, "PUT");
      setMessage({ kind: "ok", text: "Saved." });
    } catch (e) {
      fail(e);
    }
  };
  const forget = async () => {
    try {
      await api("/me/memory", null, "DELETE");
      setMessage(null);
      await load();
    } catch (e) {
      fail(e);
    }
  };
  const deleteAccount = async () => {
    try {
      await api("/me", { confirm: true }, "DELETE");
      onDeleted();
    } catch (e) {
      fail(e);
    }
  };

  return (
    <Panel title="My preferences" message={message} onClose={onClose}>
      {!form ? <div className="muted">Loading…</div> : (
        <div id="prefForm">
          <p className="muted" style={{ margin: "6px 0" }}>
            Used only for what a request does not say. Your budget is never remembered.
          </p>
          <div className="row">
            <label>Home city <input id="mHome" value={form.home_city} onChange={(e) => set("home_city", e.target.value)} /></label>
            <label>Usual way to travel{" "}
              <select id="mMode" value={form.travel_mode} onChange={(e) => set("travel_mode", e.target.value)}>
                {choices(["", "flight", "train", "bus", "car", "bike"])}
              </select>
            </label>
            <label>Pace{" "}
              <select id="mPace" value={form.pace} onChange={(e) => set("pace", e.target.value)}>
                {choices(["", "normal", "relaxed"])}
              </select>
            </label>
          </div>
          <div className="checks" style={{ marginTop: 8 }}>
            {INTERESTS.map((i) => (
              <Fragment key={i}>
                <label>
                  <input type="checkbox" className="mPref" value={i} checked={form.preferences.includes(i)}
                    onChange={(e) => toggle(i, e.target.checked)} /> {i}
                </label>{" "}
              </Fragment>
            ))}
          </div>
          <label style={{ display: "block", margin: "8px 0" }}>
            <input type="checkbox" id="mRemember" checked={form.remember}
              onChange={(e) => set("remember", e.target.checked)} /> Use these, and learn from trips I book
          </label>
          <div className="row">
            <button className="primary" id="mSave" onClick={save}>Save</button>
            <button id="mForget" onClick={forget}>Forget everything</button>
            <button className="danger" id="mDelete" onClick={() => setConfirmingDelete(true)}>Delete my account</button>
          </div>
        </div>
      )}
      {confirmingDelete && (
        <>
          <Banner kind="bad">This permanently deletes your account, saved preferences and trip list.</Banner>
          <button className="danger" id="mDeleteYes" onClick={deleteAccount}>Yes, delete my account</button>
        </>
      )}
    </Panel>
  );
}
