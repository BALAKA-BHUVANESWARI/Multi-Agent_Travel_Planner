// The trip toolkit: five helpers that use the plan and never change it.
import { useEffect, useRef, useState } from "react";
import { api, toolPath } from "../../services/api.js";
import Banner from "../common/Banner.jsx";
import CompanionTab from "./CompanionTab.jsx";
import DocumentsTab from "./DocumentsTab.jsx";
import EmergencyTab from "./EmergencyTab.jsx";
import ExpensesTab from "./ExpensesTab.jsx";
import FootprintTab from "./FootprintTab.jsx";

const TABS = [
  ["companion", "🎒 Packing & customs", CompanionTab],
  ["emergency", "🆘 Emergency", EmergencyTab],
  ["documents", "📄 Documents", DocumentsTab],
  ["footprint", "🌱 Emissions", FootprintTab],
  ["expenses", "💰 Expenses", ExpensesTab],
];

export default function Toolkit({ thread, onSignIn }) {
  const [tool, setTool] = useState("");
  const [content, setContent] = useState({ state: "idle" });
  const [actionError, setActionError] = useState(null);
  const opened = useRef("");
  const version = useRef(0);
  const errorRef = useRef(null);

  useEffect(() => {
    errorRef.current?.scrollIntoView({ block: "nearest" });
  }, [actionError]);

  // show an answer only if its tab is still the one on screen; each answer redraws the tab from scratch
  const show = (name, data) => {
    if (opened.current !== name) return;
    setActionError(null);
    setContent({ state: "ready", tool: name, data, version: ++version.current });
  };

  const open = async (name) => {
    opened.current = name;
    setTool(name);
    setActionError(null);
    setContent({ state: "loading" });
    try {
      show(name, await api(toolPath(thread, name)));
    } catch (e) {
      if (opened.current === name) setContent({ state: "failed", error: e.message });
    }
  };

  // save something, then redraw the tab with the server's answer; if it fails, what was typed stays
  const change = async (name, path, body, method) => {
    try {
      show(name, await api(path, body, method));
    } catch (e) {
      setActionError({ text: e.message });
    }
  };

  const Tab = content.state === "ready" ? TABS.find(([key]) => key === content.tool)[2] : null;
  return (
    <div className="card">
      <b>Trip toolkit</b>
      <div className="row tabs" style={{ marginTop: 8 }}>
        {TABS.map(([key, label]) => (
          <button type="button" key={key} data-tool={key} aria-pressed={tool === key} onClick={() => open(key)}>
            {label}
          </button>
        ))}
      </div>
      <div id="toolBody" className={content.state === "idle" || content.state === "loading" ? "muted" : ""}
        style={{ marginTop: 6 }}>
        {content.state === "idle" && "Choose a tool. These use your plan and never change it."}
        {content.state === "loading" && "Loading…"}
        {content.state === "failed" && <Banner kind="bad">{content.error}</Banner>}
        {Tab && (
          <>
            <div id="toolMsg" ref={errorRef}>{actionError && <Banner kind="bad">{actionError.text}</Banner>}</div>
            <div id="toolView">
              <Tab key={content.version} data={content.data} thread={thread} onSignIn={onSignIn}
                onChange={(path, body, method) => change(content.tool, path, body, method)} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
