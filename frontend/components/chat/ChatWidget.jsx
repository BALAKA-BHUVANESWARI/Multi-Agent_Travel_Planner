// The chat button and window. The chat plans, changes and answers; approving, booking and cancelling are only the
// buttons on the page. Messages are kept on this screen only and are gone after a reload.
import { useEffect, useRef, useState } from "react";
import { api } from "../../services/api.js";
import ChatPanel from "./ChatPanel.jsx";

const WELCOME = {
  from: "bot",
  text: "Hi! Tell me about your trip, by typing or with the microphone. For example: “3 days in Goa from Delhi, "
    + "budget 30000”. Once there's a plan, ask me about it or ask for changes. Booking is always done with the buttons.",
  suggestions: [],
  actions: [],
};

export default function ChatWidget({ result, busy, voice, readMembers, onResult, onClear, onShowPlan, onEmergency }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([WELCOME]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const add = (message) => setMessages((old) => [...old, { suggestions: [], actions: [], ...message }].slice(-60));

  const send = async (text) => {
    const message = text.trim();
    if (!message || sending || busy) return;
    add({ from: "you", text: message });
    setDraft("");
    setSending(true);
    try {
      const members = readMembers();
      const data = await api("/chat", {
        message,
        ...(result?.thread_id && { thread_id: result.thread_id }),
        ...(members.length && { group: members }),
      });
      if (!mounted.current) return; // signed out meanwhile: the answer belongs to the earlier traveller
      // `about` is the plan on screen that the quick replies belong to
      const about = data.result || (data.actions.includes("clear") ? null : result);
      add({ from: "bot", text: data.reply, ai: data.source === "ai", suggestions: data.suggestions,
        actions: data.actions, about });
      if (data.result) onResult(data.result);
      if (data.actions.includes("clear")) onClear();
    } catch (e) {
      if (!mounted.current) return;
      // fetch itself throws a TypeError when the server can't be reached
      add({ from: "bot", failed: true,
        text: e instanceof TypeError ? "I couldn't reach the server. Check that it's still running." : e.message });
      setDraft((now) => now || message); // so it can be sent again
    }
    setSending(false);
  };

  // on a phone the window covers the page, so it closes before showing something there
  const leaveFor = (show) => () => {
    if (window.matchMedia("(max-width: 640px)").matches) setOpen(false);
    show();
  };

  return (
    <>
      {open && (
        <ChatPanel messages={messages} draft={draft} onDraft={setDraft} onSend={send} sending={sending}
          result={result} pageBusy={busy && !sending} voice={voice} onClose={() => setOpen(false)}
          onShowPlan={leaveFor(onShowPlan)} onEmergency={leaveFor(onEmergency)} />
      )}
      <button type="button" className={`chat-launcher ${open ? "is-open" : ""}`} aria-expanded={open}
        onClick={() => setOpen((o) => !o)}>
        💬 {open ? "Close chat" : "Chat"}
      </button>
    </>
  );
}
