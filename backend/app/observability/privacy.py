"""What may be written down.

Two levels. The *basic* record (always, while recording is on) holds only names the code chose itself, numbers and
short codes: ``safe_attrs`` enforces that, so free text cannot slip in by accident. *Detailed* text (typed requests,
AI prompts and replies, retrieved text) is kept only when RECORD_DETAILS=1, and goes through ``clean_detail`` first.
"""
from __future__ import annotations

import json
import os
import re

from app.core import security as guardrails

MAX_DETAIL_CHARS = 8000
# a basic value may only look like a name or a code: no spaces, so no sentences, no typed text
_CODE = re.compile(r"[A-Za-z0-9_.:/+\-]{0,80}")
_SECRET_ENV = re.compile(r"(?:_KEY|_TOKEN|_SECRET|_PASSWORD)$")
_SECRET_SHAPES = re.compile(r"gsk_[A-Za-z0-9]{8,}|AIza[0-9A-Za-z_\-]{20,}|tvly-[A-Za-z0-9\-]{8,}|"
                            r"(?i:bearer)\s+[A-Za-z0-9._\-]{8,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_ORG_ID = re.compile(r"\borg_[A-Za-z0-9]{8,}\b")


def safe_attrs(attrs: dict) -> dict:
    """Numbers, true/false and short codes (also in a flat list or a code -> number table). Anything else is dropped."""
    out = {}
    for key, value in attrs.items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float)):
            out[key] = value
        elif isinstance(value, str) and _CODE.fullmatch(value):
            out[key] = value
        elif isinstance(value, (list, tuple)):
            out[key] = [v for v in value
                        if isinstance(v, (bool, int, float)) or isinstance(v, str) and _CODE.fullmatch(v)][:50]
        elif isinstance(value, dict):
            out[key] = {k: v for k, v in value.items()
                        if isinstance(k, str) and _CODE.fullmatch(k) and isinstance(v, (int, float))}
    return out


def code(value, default: str = "") -> str:
    """``value`` as a short code: other characters become underscores."""
    text = re.sub(r"[^A-Za-z0-9_.:/+\-]+", "_", str(value or "")).strip("_")[:80]
    return text or default


def _secrets() -> list[str]:
    return [v.strip() for k, v in os.environ.items() if _SECRET_ENV.search(k) and len(v.strip()) >= 8]


def clean_detail(value, hide=()) -> str:
    """Text that is safe to keep when detailed records are on: no keys, card or ID numbers, passwords, email
    addresses, account ids, or any of ``hide`` (group members' names, saved preferences)."""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return "[unreadable]"
    if guardrails.sensitive_kind(value):                 # the whole text is withheld, not just the number
        return guardrails.scrub(value)
    for secret in _secrets():
        value = value.replace(secret, "[key]")
    value = _SECRET_SHAPES.sub("[key]", value)
    value = _EMAIL.sub("[email]", value)
    value = _ORG_ID.sub("[account]", value)
    for word in sorted({str(h).strip() for h in hide if len(str(h).strip()) >= 2}, key=len, reverse=True):
        value = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", "[hidden]", value, flags=re.I)
    return value[:MAX_DETAIL_CHARS]
