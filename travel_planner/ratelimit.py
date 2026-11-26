"""Rate limits for this app's own API (sliding window, in memory, per signed-in user or client address).

It protects the free-tier quotas behind the planner and slows down password guessing. Being in memory, the
counts reset on restart and are per process, which is right for one local server.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Callable

from . import config

MAX_KEYS = 10_000


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"Too many requests. Please wait {retry_after} second(s) and try again.")
        self.retry_after = retry_after


def default_rules() -> dict:
    """bucket -> [(allowed requests, window in seconds), ...]"""
    return {
        "plan": [(config.rate_limit("PLAN_PER_MINUTE", 10), 60), (config.rate_limit("PLAN_PER_DAY", 200), 86400)],
        "act": [(config.rate_limit("ACTIONS_PER_MINUTE", 30), 60)],
        "auth": [(config.rate_limit("AUTH_PER_MINUTE", 8), 60), (40, 3600)],
        "read": [(config.rate_limit("READS_PER_MINUTE", 120), 60)],
    }


class RateLimiter:
    def __init__(self, rules: dict | None = None, clock: Callable[[], float] = time.monotonic):
        self.rules = rules if rules is not None else default_rules()
        self.clock = clock
        self._hits: dict[tuple[str, str], deque] = {}
        self._lock = threading.Lock()

    def check(self, bucket: str, key: str) -> None:
        """Record one request, or raise RateLimited (a refused request is not counted)."""
        limits = self.rules.get(bucket)
        if not limits:
            return
        now = self.clock()
        longest = max(w for _, w in limits)
        with self._lock:
            if len(self._hits) >= MAX_KEYS:                       # never let the table grow without bound
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < 3600}
            hits = self._hits.setdefault((bucket, key), deque())
            while hits and now - hits[0] >= longest:
                hits.popleft()
            waits = []
            for allowed, window in limits:
                recent = [t for t in hits if now - t < window]
                if len(recent) >= allowed:
                    waits.append(window - (now - recent[len(recent) - allowed]) if allowed > 0 else window)
            if waits:
                raise RateLimited(max(1, math.ceil(max(waits))))
            hits.append(now)
