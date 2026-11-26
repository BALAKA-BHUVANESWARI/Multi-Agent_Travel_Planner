"""Input guardrails + sanitising of untrusted (tool / web) text.

Rules first (cheap, deterministic, explainable). Never echo sensitive values back.
"""
from __future__ import annotations

import re

from app.core import config
from app.data.curated_destinations import ALIASES

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier|instructions?|rules?)",
    r"forget\s+(everything|all|your\s+instructions?|the\s+rules)",
    r"(reveal|show|print|repeat|leak|display)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions?|rules)",
    r"\byou\s+are\s+now\b",
    r"\bact\s+as\s+(?!a\s+travel)",
    r"\bpretend\s+(to\s+be|you\s+are)\b",
    r"developer\s+mode|\bjailbreak\b|\bdan\s+mode\b",
    r"</?\s*(system|assistant|developer)\s*>",
    r"override\s+(your|the)\s+(rules|instructions|guidelines|safety)",
    r"new\s+instructions?\s*:",
    r"\bsystem\s+prompt\b",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]

TRAVEL_WORDS = {
    "trip", "travel", "travelling", "traveling", "plan", "visit", "holiday", "vacation", "itinerary",
    "days", "day", "nights", "night", "flight", "flights", "hotel", "hotels", "tour", "getaway", "honeymoon",
    "weekend", "budget", "stay", "explore", "sightseeing", "backpacking", "journey", "go", "going",
}
_DEST_WORDS = {a for aliases in ALIASES.values() for a in aliases}


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)|(?<!\d)\d{12}(?!\d)")
_OTP = re.compile(r"\b(otp|one[- ]time\s+(password|passcode|code)|verification\s+code)\b[^\n]{0,25}?\b\d{4,8}\b"
                  r"|\b\d{4,8}\b[^\n]{0,15}\b(otp|one[- ]time\s+(password|passcode|code))\b", re.I)
_CVV = re.compile(r"\bcvv2?\b|\bcvc\b", re.I)
_PASSWORD = re.compile(r"\b(password|passwd|pin\s*code|upi\s*pin|atm\s*pin)\b\s*(is|:|=)", re.I)
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


def _sensitive(text: str) -> str | None:
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            return "card number"
    if _AADHAAR.search(text):
        return "government ID number"
    if _OTP.search(text):
        return "OTP / verification code"
    if _CVV.search(text):
        return "card security code"
    if _PASSWORD.search(text):
        return "password or PIN"
    if _PAN.search(text):
        return "PAN number"
    return None


WITHHELD = "[withheld: contains a "


def scrub(text: str) -> str:
    """Replace a message that contains a card/ID number, OTP or password with a placeholder. Called before the
    message reaches the planner, so the secret is never stored in a checkpoint, a trace or an API response;
    `check_input` still refuses the placeholder with the same message."""
    kind = _sensitive(text) if isinstance(text, str) else None
    return f"{WITHHELD}{kind}]" if kind else text


def _on_topic(text: str) -> bool:
    low = text.lower()
    words = set(re.findall(r"[a-z]+", low))
    if words & TRAVEL_WORDS:
        return True
    return any(re.search(rf"\b{re.escape(a)}\b", low) for a in _DEST_WORDS)


def check_input(text: str, require_topic: bool = True) -> dict:
    """Return {allowed, code, message}. Order: empty, length, injection, sensitive, off-topic."""
    if not text or not text.strip():
        return {"allowed": False, "code": "empty", "message": "Please describe the trip you want to plan."}
    if len(text) > config.MAX_REQUEST_CHARS:
        return {"allowed": False, "code": "too_long",
                "message": f"That request is too long (limit {config.MAX_REQUEST_CHARS} characters)."}
    for pat in _INJ:
        if pat.search(text):
            return {"allowed": False, "code": "prompt_injection",
                    "message": "I can't follow instructions that try to change my rules. "
                               "Tell me about the trip you want instead."}
    kind = _sensitive(text)
    if not kind and text.startswith(WITHHELD):
        kind = text[len(WITHHELD):].rstrip("]") or "sensitive detail"
    if kind:
        return {"allowed": False, "code": "sensitive_data",
                "message": f"Your message appears to contain a {kind}. Please don't share that here - "
                           "nothing is paid for in this planner. Resend the request without it."}
    if require_topic and not _on_topic(text):
        return {"allowed": False, "code": "off_topic",
                "message": "I only plan trips (flights, hotel, weather, day-by-day activities, budget). "
                           "Try: 'Plan a 5 day trip to Goa from Delhi in December, budget 60k for 2'."}
    return {"allowed": True, "code": "ok", "message": ""}


_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def sanitize_untrusted(text: str, max_len: int = 400) -> str:
    """Treat tool/web text as data: strip control chars, neutralise injection phrases, truncate."""
    if not isinstance(text, str):
        return ""
    text = _CTRL.sub(" ", text)
    for pat in _INJ:
        text = pat.sub("[removed]", text)
    text = re.sub(r"<[^>]{0,80}>", " ", text)          # strip markup-ish fragments
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]
