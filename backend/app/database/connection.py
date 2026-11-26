"""Opening the SQLite database."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def open_connection(path: str = ":memory:") -> sqlite3.Connection:
    """A connection that may be shared between threads (callers serialise access with their own lock)."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path, check_same_thread=False)
