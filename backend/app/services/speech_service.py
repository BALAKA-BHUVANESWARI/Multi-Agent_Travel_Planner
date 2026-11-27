"""Voice input: turn a short recording into text with Groq's Whisper (free tier; verify the limits in the console).

The recording is passed straight to Groq and is never written to disk or kept. The text goes back to the page for
the traveller to check and edit; nothing is done with it until they press Send.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
import uuid
from typing import Callable

from app.core import config
from app.observability import recorder as observe

log = logging.getLogger(__name__)

ENDPOINT = "/audio/transcriptions"
MAX_AUDIO_BYTES = 4 * 1024 * 1024          # a one-minute browser recording is well under this
MIN_AUDIO_BYTES = 1000
TIMEOUT = 30
DEFAULT_MODEL = "whisper-large-v3-turbo"
DEFAULT_DAILY_LIMIT = 100                  # recordings a day from this app, well under the provider's own limit
# what browsers record (and a few common files) -> the file ending Groq needs to see
TYPES = {"audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "video/mp4": "mp4",
         "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
         "audio/flac": "flac"}


class SpeechError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def available(env=None) -> bool:
    env = os.environ if env is None else env
    return bool(str(env.get("GROQ_API_KEY") or "").strip())


def _daily_limit(env) -> int:
    try:
        return max(0, int(env.get("VOICE_DAILY_LIMIT", DEFAULT_DAILY_LIMIT)))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_LIMIT


def multipart(fields: dict, filename: str, content_type: str, audio: bytes) -> tuple[bytes, str]:
    """(body, Content-Type header) for a file upload, with the standard library only."""
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f"Content-Type: {content_type}\r\n\r\n".encode() + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _error_body(raw: str) -> dict:
    """Groq's error answer as a dict. A non-JSON answer (a block page) is kept as a short tag-free snippet."""
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict):
        return data
    return {"error": {"message": " ".join(re.sub(r"<[^>]+>", " ", raw).split())[:300]}}


def _reason(data, key: str) -> tuple[str, str]:
    """(error code, message) from Groq's answer, safe to print: the key is removed."""
    err = data.get("error") if isinstance(data, dict) else None
    code, message = (err.get("code"), err.get("message")) if isinstance(err, dict) else (None, err)
    code = re.sub(r"[^a-z0-9_]", "", str(code or "").lower())[:60]
    message = " ".join(str(message or "").split())
    return code, message.replace(key, "***")[:300]


def _refusal(status: int, code: str, model: str) -> str:
    """What the page says when Groq says no. A 401 is about the key; a 403 usually isn't."""
    if status == 401:
        return ("Groq didn't accept the API key (error 401). Check GROQ_API_KEY in .env and restart the server. "
                "You can still type.")
    levels = {"model_permission_blocked_org": ("organization", "https://console.groq.com/settings/limits"),
              "model_permission_blocked_project": ("project", "https://console.groq.com/settings/project/limits")}
    if code in levels:
        level, page = levels[code]
        return (f"The voice model {model} is blocked in your Groq {level} settings. Allow it at {page} . "
                "You can still type.")
    return ("Groq refused the voice request (error 403). The server window shows Groq's reason. "
            "You can still type.")


def default_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:        # noqa: S310
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "replace")
        except OSError:
            raw = ""
        return e.code, _error_body(raw)


def transcribe(audio: bytes, content_type: str, *, env=None, store=None, transport: Callable | None = None) -> str:
    env = os.environ if env is None else env
    if not available(env):
        raise SpeechError(503, "Voice input needs a Groq API key (GROQ_API_KEY in .env). You can still type.")
    kind = str(content_type or "").split(";")[0].strip().lower()
    if kind not in TYPES:
        raise SpeechError(415, "This recording format isn't supported. Please type your message.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise SpeechError(413, "That recording is too long. Keep it under a minute.")
    if len(audio) < MIN_AUDIO_BYTES:
        raise SpeechError(422, "I didn't get any sound. Hold the recording a little longer.")
    if store is not None:
        if store.count("stt:groq") >= _daily_limit(env):
            observe.event("guardrail", "rate_limit", "blocked", bucket="voice_daily")
            raise SpeechError(429, "Today's voice limit is used up. You can still type.")
        store.bump("stt:groq")
    # English only for now: the planner reads English. Other languages need testing first.
    fields = {"model": env.get("GROQ_WHISPER_MODEL") or DEFAULT_MODEL, "language": "en",
              "response_format": "json", "temperature": "0"}
    body, body_type = multipart(fields, f"speech.{TYPES[kind]}", kind, audio)
    key = str(env.get("GROQ_API_KEY")).strip()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": body_type, "Accept": "application/json",
               "User-Agent": config.HTTP_USER_AGENT}
    url = config.PROVIDERS["groq"][0] + ENDPOINT
    # the size, time and result are recorded; the sound and the words never are
    with observe.span("voice", "groq.transcribe", model=fields["model"], audio_bytes=len(audio)) as call:
        try:
            status, data = (transport or default_transport)(url, headers, body, TIMEOUT)
        except (OSError, ValueError):                       # network failure or unreadable answer
            call.fail("network")
            raise SpeechError(502, "I couldn't reach the voice service. Please try again, or type.")
        call.set(http_status=status)
        if status != 200:                                   # the reason goes to the server window, never the key
            code, reason = _reason(data, key)
            call.fail("http_error", provider_code=code or None)
            log.warning("Groq voice request failed: HTTP %s %s %s", status, code, reason)
    if status == 429:
        raise SpeechError(429, "The voice service is busy or its free limit is reached. Try later, or type.")
    if status in (401, 403):
        raise SpeechError(503, _refusal(status, code, fields["model"]))
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("text"), str):
        raise SpeechError(502, "The voice service couldn't read that recording. Please try again, or type.")
    text = " ".join(data["text"].split())
    if not text:
        raise SpeechError(422, "I didn't catch any words. Please try again.")
    return text[: config.MAX_REQUEST_CHARS]
