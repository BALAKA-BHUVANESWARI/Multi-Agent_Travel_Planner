"""Recording settings, read from the environment (.env)."""
from __future__ import annotations

import os

from app.core import config


def enabled() -> bool:
    """OBSERVABILITY=0 switches recording off."""
    return config.env_bool("OBSERVABILITY", True)


def details_enabled() -> bool:
    """RECORD_DETAILS=1 also keeps typed requests, AI prompts and replies, and retrieved text. Off by default."""
    return config.env_bool("RECORD_DETAILS", False)


def db_path() -> str:
    return config.runtime_path(os.environ.get("OBSERVABILITY_DB"), "observability.db")


def _days(name: str, default: int) -> int:
    try:
        return min(365, max(1, int(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


MIN_PASSWORD = 8


def dashboard_on() -> bool:
    """DASHBOARD=1 switches the dashboard on (it also needs DASHBOARD_PASSWORD). Off by default."""
    return config.env_bool("DASHBOARD", False)


def dashboard_password() -> str:
    return str(os.environ.get("DASHBOARD_PASSWORD") or "").strip()


def keep_days() -> int:
    return _days("RECORD_KEEP_DAYS", 30)


def detail_keep_days() -> int:
    return _days("RECORD_DETAIL_KEEP_DAYS", 7)
