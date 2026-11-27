// The chat window: messages, quick replies, the text box and the microphone.
import { useEffect, useRef } from "react";
import { canRecord, MAX_SECONDS, useVoiceInput } from "../../hooks/useVoiceInput.js";

const MAX_CHARS = 1000;
const MIC_LABEL = { idle: "Speak", starting: "Starting…", recording: "Stop", working: "Reading…" };

function Message({ message, latest, outdated, busy, onSend, onShowPlan, onEmergency }) {
  return (
    <div className={`chat-msg ${message.from} ${message.failed ? "failed" : ""}`}>
      <div className="bubble">
        {message.text}
        {message.ai && <div className="chat-ai">AI answer based on your plan. Check important details.</div>}
        {message.actions?.includes("show_plan") && (
          <button type="button" className="chat-link" onClick={onShowPlan}>Show the plan →</button>
        )}
        {message.actions?.includes("open_emergency") && (
          <button type="button" className="chat-link" onClick={onEmergency}>Open emergency help →</button>
        )}
      </div>
      {latest && message.suggestions?.length > 0 && outdated && (
        <p className="chat-note">The page has changed since this question, so its options are gone. Type what you want
          next.</p>
      )}
      {latest && message.suggestions?.length > 0 && !outdated && (
        <div className="chat-chips">
          {message.suggestions.map((s) => (
            <button type="button" key={s.label} disabled={busy} onClick={() => onSend(s.send)}>{s.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ChatPanel({ messages, draft, onDraft, onSend, sending, result, pageBusy, voice, onClose,
  onShowPlan, onEmergency }) {
  const busy = sending || pageBusy;
  const end = useRef(null);
  const box = useRef(null);
  const recorder = useVoiceInput((text) => {
    onDraft((now) => `${now} ${text}`.trim().slice(0, MAX_CHARS));
    box.current?.focus();
  });
  const recording = recorder.state === "recording";
  const listening = recorder.state !== "idle";
  const micMissing = !canRecord() ? "This browser can't record audio, so please type."
    : voice === false ? "Voice input needs a Groq API key. You can type." : "";

  // braces matter: an effect must return nothing, and some browsers return a value from scrollIntoView
  useEffect(() => {
    box.current?.focus();
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages.length, sending, pageBusy]);

  const submit = (e) => {
    e.preventDefault();
    if (!listening) onSend(draft);
  };

  return (
    <section className="chat-panel" role="dialog" aria-label="Trip chat"
      onKeyDown={(e) => e.key === "Escape" && onClose()}>
      <header>
        <b>💬 Trip chat</b>
        <button type="button" className="chat-close" onClick={onClose} aria-label="Close chat">✕</button>
      </header>

      <div className="chat-log" aria-live="polite">
        {messages.map((message, i) => (
          <Message key={i} message={message} latest={i === messages.length - 1} busy={busy} onSend={onSend}
            outdated={!pageBusy && message.about !== result} onShowPlan={onShowPlan} onEmergency={onEmergency} />
        ))}
        {sending && <div className="chat-msg bot"><div className="bubble muted">Working on it…</div></div>}
        {pageBusy && (
          <p className="chat-note">The page is still working on a plan. You can pick or send here when it finishes.</p>
        )}
        <div ref={end} />
      </div>

      <form onSubmit={submit}>
        <textarea ref={box} rows={2} maxLength={MAX_CHARS} value={draft} aria-label="Message"
          placeholder="Type a message…" onChange={(e) => onDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
          }} />
        <div className="chat-actions">
          <button type="button" className={`chat-mic ${recording ? "on" : ""}`} aria-pressed={recording}
            disabled={Boolean(micMissing) || recorder.state === "starting" || recorder.state === "working"}
            title={micMissing || "Record a message"} onClick={recording ? recorder.stop : recorder.start}>
            🎤 {MIC_LABEL[recorder.state]}
          </button>
          {listening && <button type="button" className="chat-cancel" onClick={recorder.cancel}>Discard</button>}
          <button type="submit" className="primary chat-send" disabled={busy || listening || !draft.trim()}>
            Send
          </button>
        </div>
        <p className="chat-hint" role="status">
          {recording ? `Recording ${recorder.seconds}s of ${MAX_SECONDS}s. Press Stop when you're done.`
            : recorder.error ? <span className="chat-error">{recorder.error}</span>
              : micMissing || "Speech becomes text for you to check before sending. Recordings go to Groq, so don't "
                + "say card or ID numbers or passwords."}
        </p>
      </form>
    </section>
  );
}
