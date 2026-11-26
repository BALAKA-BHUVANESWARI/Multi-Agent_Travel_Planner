"""Small shared helpers (pure functions)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.core import config


def hash01(*parts) -> float:
    """Deterministic pseudo-random float in [0, 1) from the given parts."""
    h = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:12], 16) / float(16 ** 12)


def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(mins: float) -> str:
    mins = int(round(mins))
    return f"{mins // 60:02d}:{mins % 60:02d}"


def fmt_inr(n) -> str:
    """Indian digit grouping: 1234567 -> ₹12,34,567."""
    n = int(round(n))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + "₹" + s


def round_to(n: float, step: int = 50) -> int:
    return int(round(n / step) * step)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def next_strategy(strategy: str) -> str:
    i = config.STRATEGIES.index(strategy)
    return config.STRATEGIES[min(i + 1, len(config.STRATEGIES) - 1)]


def strategy_rank(strategy: str) -> int:
    return config.STRATEGIES.index(strategy)


def clip(text: str, n: int) -> str:
    """Shorten to at most ~n chars on a sentence (else word) boundary, adding an ellipsis if cut."""
    text = " ".join(str(text).split())
    if len(text) <= n:
        return text
    cut = text[:n]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end > n * 0.5:
        return cut[:end + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:-") + "…"
