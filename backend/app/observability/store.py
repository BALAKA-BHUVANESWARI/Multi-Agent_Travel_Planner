"""The records database (.runtime/observability.db), kept apart from the planner's own database."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from app.database.connection import open_connection

MAX_RUNS = 5000                    # a hard limit on size, besides the age limit

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, parent_id TEXT, kind TEXT NOT NULL, thread_id TEXT,
    owner TEXT, status TEXT, engine TEXT, started TEXT NOT NULL, duration_ms REAL, attrs TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS spans(id TEXT PRIMARY KEY, run_id TEXT NOT NULL, parent_id TEXT, type TEXT NOT NULL,
    name TEXT NOT NULL, start_ms REAL NOT NULL, duration_ms REAL NOT NULL, status TEXT NOT NULL, attrs TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS details(run_id TEXT NOT NULL, span_id TEXT, name TEXT NOT NULL, content TEXT NOT NULL,
    created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS marks(span_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, verdict TEXT NOT NULL,
    created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS spans_by_run ON spans(run_id);
CREATE INDEX IF NOT EXISTS details_by_run ON details(run_id);
CREATE INDEX IF NOT EXISTS runs_by_time ON runs(started);
"""


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds")


def now() -> datetime:
    return datetime.now(timezone.utc)


class RecordStore:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._conn = open_connection(path)
        self._lock = threading.RLock()
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")     # records are not worth a slow disk flush
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # -- writing (each call is one transaction)
    def write(self, run: dict | None = None, spans: list | None = None, details: list | None = None) -> None:
        with self._lock, self._conn:
            if run:
                self._conn.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?,?,?,?,?)",
                                   (run["id"], run["parent_id"], run["kind"], run["thread_id"], run["owner"],
                                    run["status"], run["engine"], run["started"], run["duration_ms"],
                                    json.dumps(run["attrs"])))
            for s in spans or []:
                self._conn.execute("INSERT OR REPLACE INTO spans VALUES(?,?,?,?,?,?,?,?,?)",
                                   (s["id"], s["run_id"], s["parent_id"], s["type"], s["name"], s["start_ms"],
                                    s["duration_ms"], s["status"], json.dumps(s["attrs"])))
            for d in details or []:
                self._conn.execute("INSERT INTO details VALUES(?,?,?,?,?)",
                                   (d["run_id"], d["span_id"], d["name"], d["content"], _iso(now())))

    # -- removing
    def _drop_orphans(self) -> None:
        self._conn.execute("DELETE FROM spans WHERE run_id NOT IN (SELECT id FROM runs)")
        self._conn.execute("DELETE FROM details WHERE run_id NOT IN (SELECT id FROM runs)")
        self._conn.execute("DELETE FROM marks WHERE run_id NOT IN (SELECT id FROM runs)")

    def prune(self, keep_days: int, detail_keep_days: int, max_runs: int = MAX_RUNS) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM runs WHERE started < ?", (_iso(now() - timedelta(days=keep_days)),))
            self._conn.execute("DELETE FROM runs WHERE id IN (SELECT id FROM runs ORDER BY started DESC "
                               "LIMIT -1 OFFSET ?)", (max_runs,))
            self._conn.execute("DELETE FROM details WHERE created < ?",
                               (_iso(now() - timedelta(days=detail_keep_days)),))
            self._drop_orphans()

    def forget(self, *, thread_id: str | None = None, owner: str | None = None) -> None:
        """Remove everything recorded for a deleted trip or account."""
        with self._lock, self._conn:
            if thread_id:
                self._conn.execute("DELETE FROM runs WHERE thread_id=?", (thread_id,))
            if owner:
                self._conn.execute("DELETE FROM runs WHERE owner=?", (owner,))
            self._drop_orphans()

    # -- the owner's own judgement of a flagged fact check: the only thing the dashboard writes
    def set_mark(self, span_id: str, verdict: str) -> bool:
        """``verdict`` "" removes the mark. False when there is no flagged check with this id."""
        with self._lock, self._conn:
            found = self._conn.execute("SELECT run_id FROM spans WHERE id=? AND type='fact_check' "
                                       "AND status='flagged'", (span_id,)).fetchone()
            if not found:
                return False
            if verdict:
                self._conn.execute("INSERT OR REPLACE INTO marks VALUES(?,?,?,?)",
                                   (span_id, found[0], verdict, _iso(now())))
            else:
                self._conn.execute("DELETE FROM marks WHERE span_id=?", (span_id,))
            return True

    def marks(self) -> dict:
        with self._lock:
            return dict(self._conn.execute("SELECT span_id, verdict FROM marks"))

    # -- reading (used by the tests now and by the dashboard next)
    def _rows(self, sql: str, args=()) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(sql, args)
            names = [c[0] for c in cursor.description]
            rows = [dict(zip(names, r)) for r in cursor.fetchall()]
        for row in rows:
            if "attrs" in row:
                row["attrs"] = json.loads(row["attrs"])
        return rows

    def runs(self, limit: int = 200) -> list[dict]:
        return self._rows("SELECT * FROM runs ORDER BY started DESC, rowid DESC LIMIT ?", (limit,))

    def find_runs(self, since: str | None = None, until: str | None = None, kind: str | None = None,
                  status: str | None = None) -> list[dict]:
        """Newest first. ``since`` (included) and ``until`` (excluded) are UTC times as stored."""
        where, args = [], []
        for clause, value in (("started >= ?", since), ("started < ?", until), ("kind = ?", kind),
                              ("status = ?", status)):
            if value:
                where.append(clause)
                args.append(value)
        sql = "SELECT * FROM runs" + (" WHERE " + " AND ".join(where) if where else "")
        return self._rows(sql + " ORDER BY started DESC, rowid DESC", args)

    def run(self, run_id: str) -> dict | None:
        rows = self._rows("SELECT * FROM runs WHERE id=?", (run_id,))
        return rows[0] if rows else None

    def linked_runs(self, run: dict) -> list[dict]:
        """Other requests about the same trip, and the request this one came from or started."""
        return self._rows("SELECT * FROM runs WHERE id != ? AND (id = ? OR parent_id = ? OR "
                          "(thread_id IS NOT NULL AND thread_id = ?)) ORDER BY started, rowid",
                          (run["id"], run["parent_id"], run["id"], run["thread_id"]))

    def spans_of(self, run_ids: list) -> dict:
        """run id -> its steps, in the order they started."""
        found: dict = {run_id: [] for run_id in run_ids}
        for start in range(0, len(run_ids), 500):                  # SQLite limits the length of a list
            chunk = run_ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            for span in self._rows(f"SELECT * FROM spans WHERE run_id IN ({marks}) ORDER BY start_ms, rowid", chunk):
                found[span["run_id"]].append(span)
        return found

    def details_of(self, run_ids: list) -> list[dict]:
        found: list = []
        for start in range(0, len(run_ids), 500):
            chunk = run_ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            found += self._rows(f"SELECT * FROM details WHERE run_id IN ({marks}) ORDER BY rowid", chunk)
        return found

    def choices(self) -> dict:
        """The agents and models seen, and how many requests are kept, without reading every step."""
        with self._lock:
            agents = [r[0] for r in self._conn.execute("SELECT DISTINCT name FROM spans WHERE type='agent'")]
            models = [r[0] for r in self._conn.execute(
                "SELECT DISTINCT json_extract(attrs, '$.model') FROM spans WHERE type IN ('llm_call', 'voice')")]
            count, oldest, newest = self._conn.execute("SELECT COUNT(*), MIN(started), MAX(started) FROM runs").fetchone()
        return {"agents": agents, "models": [m for m in models if m], "recorded": count, "oldest": oldest,
                "newest": newest}

    def spans(self, run_id: str | None = None) -> list[dict]:
        if run_id:
            return self._rows("SELECT * FROM spans WHERE run_id=? ORDER BY start_ms, rowid", (run_id,))
        return self._rows("SELECT * FROM spans ORDER BY rowid")

    def details(self, run_id: str | None = None) -> list[dict]:
        if run_id:
            return self._rows("SELECT * FROM details WHERE run_id=? ORDER BY rowid", (run_id,))
        return self._rows("SELECT * FROM details ORDER BY rowid")
