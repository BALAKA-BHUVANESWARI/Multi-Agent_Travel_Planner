"""SQLite persistence: checkpoints (resume by thread_id), bookings (idempotency),
LLM response cache, daily call counters."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import date

from .utils import now_iso


class Store:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS checkpoints(thread_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bookings(idempotency_key TEXT PRIMARY KEY, thread_id TEXT, booking TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS llm_cache(key TEXT PRIMARY KEY, value TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS counters(name TEXT, day TEXT, n INTEGER NOT NULL, PRIMARY KEY(name, day));
            CREATE TABLE IF NOT EXISTS trip_items(thread_id TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL,
                data TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(thread_id, kind, item_id));
            """)
            self._conn.commit()

    # -- checkpoints
    def save_state(self, thread_id: str, state: dict) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)",
                               (thread_id, json.dumps(state, default=str), now_iso()))
            self._conn.commit()

    def load_state(self, thread_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT state FROM checkpoints WHERE thread_id=?", (thread_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def delete_trip(self, thread_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM checkpoints WHERE thread_id=?", (thread_id,))
            self._conn.execute("DELETE FROM bookings WHERE thread_id=?", (thread_id,))
            self._conn.execute("DELETE FROM trip_items WHERE thread_id=?", (thread_id,))
            self._conn.commit()

    def list_threads(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute("SELECT thread_id FROM checkpoints ORDER BY updated DESC")]

    # -- bookings (idempotent)
    def get_booking(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT booking FROM bookings WHERE idempotency_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_booking(self, key: str, thread_id: str, booking: dict) -> dict:
        """Insert-if-absent; always returns the stored booking (first writer wins)."""
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO bookings VALUES(?,?,?,?)",
                               (key, thread_id, json.dumps(booking), now_iso()))
            self._conn.commit()
        return self.get_booking(key)  # type: ignore[return-value]

    def add_cancellation(self, key: str, cancellation: dict) -> dict:
        """Attach a cancellation to a booking (first writer wins); returns the stored booking."""
        with self._lock:
            booking = self.get_booking(key)
            if booking is None:
                raise KeyError(key)
            if not booking.get("cancellation"):
                booking = {**booking, "cancellation": cancellation, "status": cancellation["status"]}
                self._conn.execute("UPDATE bookings SET booking=? WHERE idempotency_key=?", (json.dumps(booking), key))
                self._conn.commit()
        return booking

    def booking_count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]

    # -- a trip's own records (documents, expenses)
    def list_items(self, thread_id: str, kind: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT item_id, data FROM trip_items WHERE thread_id=? AND kind=? "
                                      "ORDER BY created, rowid", (thread_id, kind)).fetchall()
        return [{**json.loads(data), "id": item_id} for item_id, data in rows]

    def add_item(self, thread_id: str, kind: str, data: dict, limit: int) -> dict:
        """Store a new record; raises ValueError when the trip already has ``limit`` of this kind."""
        item_id = uuid.uuid4().hex[:12]
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM trip_items WHERE thread_id=? AND kind=?",
                                   (thread_id, kind)).fetchone()[0]
            if n >= limit:
                raise ValueError(f"This trip already has {limit} entries. Delete one first.")
            self._conn.execute("INSERT INTO trip_items VALUES(?,?,?,?,?)",
                               (thread_id, kind, item_id, json.dumps(data), now_iso()))
            self._conn.commit()
        return {**data, "id": item_id}

    def update_item(self, thread_id: str, kind: str, item_id: str, data: dict) -> bool:
        with self._lock:
            done = self._conn.execute("UPDATE trip_items SET data=? WHERE thread_id=? AND kind=? AND item_id=?",
                                      (json.dumps(data), thread_id, kind, item_id)).rowcount
            self._conn.commit()
        return bool(done)

    def delete_item(self, thread_id: str, kind: str, item_id: str) -> bool:
        with self._lock:
            done = self._conn.execute("DELETE FROM trip_items WHERE thread_id=? AND kind=? AND item_id=?",
                                      (thread_id, kind, item_id)).rowcount
            self._conn.commit()
        return bool(done)

    # -- llm cache
    def cache_get(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM llm_cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_set(self, key: str, value: dict) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO llm_cache VALUES(?,?,?)",
                               (key, json.dumps(value), now_iso()))
            self._conn.commit()

    # -- counters
    def bump(self, name: str, today: str | None = None) -> int:
        day = today or date.today().isoformat()
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO counters VALUES(?,?,0)", (name, day))
            self._conn.execute("UPDATE counters SET n=n+1 WHERE name=? AND day=?", (name, day))
            self._conn.commit()
            return self._conn.execute("SELECT n FROM counters WHERE name=? AND day=?", (name, day)).fetchone()[0]

    def count(self, name: str, today: str | None = None) -> int:
        day = today or date.today().isoformat()
        with self._lock:
            row = self._conn.execute("SELECT n FROM counters WHERE name=? AND day=?", (name, day)).fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
