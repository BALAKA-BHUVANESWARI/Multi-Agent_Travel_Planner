// Voice input: record with the browser's microphone, then ask the backend to turn the recording into text.
// The microphone is on only while recording, and the text is handed back for the traveller to check.
import { useCallback, useEffect, useRef, useState } from "react";
import { apiUpload } from "../services/api.js";

export const MAX_SECONDS = 60;
const FORMATS = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];

export const canRecord = () => Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);

export function useVoiceInput(onText) {
  const [state, setState] = useState("idle"); // idle | starting | recording | working
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  // each use of the microphone is one "take"; a cancelled take is never sent or shown
  const take = useRef(null);
  const handler = useRef(onText);
  handler.current = onText;

  const cancel = useCallback(() => {
    const current = take.current;
    take.current = null;
    if (current) {
      current.cancelled = true;
      if (current.recorder?.state === "recording") current.recorder.stop();
      current.stream?.getTracks().forEach((track) => track.stop());
    }
    setState("idle");
  }, []);

  const stop = useCallback(() => {
    const recorder = take.current?.recorder;
    if (recorder?.state === "recording") recorder.stop();
  }, []);

  const start = useCallback(async () => {
    if (take.current) return;
    const current = { cancelled: false };
    take.current = current;
    setError("");
    setSeconds(0);
    setState("starting");
    const fail = (message) => {
      if (take.current !== current) return;
      current.stream?.getTracks().forEach((track) => track.stop());
      take.current = null;
      setState("idle");
      setError(message);
    };
    try {
      current.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      fail(e.name === "NotAllowedError"
        ? "The microphone is blocked. Allow it in your browser's site settings, or type."
        : "I couldn't use a microphone. Check that one is connected, or type.");
      return;
    }
    if (current.cancelled) {
      current.stream.getTracks().forEach((track) => track.stop());
      return;
    }
    try {
      const mimeType = FORMATS.find((f) => MediaRecorder.isTypeSupported(f));
      const recorder = new MediaRecorder(current.stream, { ...(mimeType && { mimeType }), audioBitsPerSecond: 32000 });
      const chunks = [];
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.onstop = async () => {
        current.stream.getTracks().forEach((track) => track.stop());
        if (current.cancelled) return;
        setState("working");
        try {
          const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || "audio/webm" });
          const { text } = await apiUpload("/transcribe", blob);
          if (current.cancelled) return;
          take.current = null;
          setState("idle");
          handler.current(text);
        } catch (e) {
          fail(e.message);
        }
      };
      current.recorder = recorder;
      recorder.start();
      setState("recording");
    } catch {
      fail("This browser couldn't record. Please type your message.");
    }
  }, []);

  useEffect(() => {
    if (state !== "recording") return undefined;
    const started = Date.now();
    const timer = setInterval(() => {
      const passed = Math.floor((Date.now() - started) / 1000);
      setSeconds(passed);
      if (passed >= MAX_SECONDS) stop();
    }, 250);
    return () => clearInterval(timer);
  }, [state, stop]);

  useEffect(() => cancel, [cancel]); // leaving the chat releases the microphone

  return { state, seconds, error, start, stop, cancel };
}
