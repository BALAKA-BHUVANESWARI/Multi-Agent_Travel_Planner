"""Tiny on-disk JSON cache for slow, rate-limited free services (Overpass, Wikipedia).

A place's sights do not change from one day to the next, so a successful lookup is kept for 30 days:
a repeat request for the same destination is instant and still works while the free service is down.
Everything is best-effort: any disk problem is ignored and the live call is simply made.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from app.core import config
from app.observability import recorder as observe

TTL_SECONDS = 30 * 24 * 3600


def cache_dir() -> Path:
    override = os.environ.get("TRIP_CACHE_DIR")
    return Path(override) if override else Path(config.db_path()).resolve().parent / "place_cache"


def _file(key: str) -> Path:
    return cache_dir() / (hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")


def get(key: str, ttl: float = TTL_SECONDS, record: bool = True):
    try:
        data = json.loads(_file(key).read_text(encoding="utf-8"))
        if time.time() - float(data["saved"]) <= ttl and data.get("key") == key:
            if record:
                observe.note_cache(True)
            return data["value"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if record:
        observe.note_cache(False)
    return None


def put(key: str, value) -> None:
    try:
        d = cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        _file(key).write_text(json.dumps({"key": key, "saved": time.time(), "value": value}), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass
