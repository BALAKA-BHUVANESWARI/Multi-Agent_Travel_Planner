"""Local accounts, sessions, saved traveller preferences ("memory") and each user's trips.

Zero cost and local: SQLite plus the standard library. Passwords are stored only as salted scrypt hashes and
session tokens only as SHA-256 hashes. The token travels in an ``Authorization: Bearer`` header (never a
cookie), so another website cannot make the browser send it. This suits a local or demo deployment; before
putting it on the internet, serve it over HTTPS.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
import uuid
from typing import Callable

from app.core.utils import now_iso
from app.database.models import ACCOUNT_TABLES
from app.services.pricing.transport_estimator import MODES
from app.services.request_parser import PREF_WORDS

SESSION_SECONDS = 7 * 24 * 3600
MIN_PASSWORD, MAX_PASSWORD = 8, 128
MAX_TRIPS_LISTED = 50
DELETED = "deleted-account"      # owner marker; real user ids are 32 hex characters
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s.]{2,24}$")
_PLACE = re.compile(r"^[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ .'’-]{1,59}$")
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


class AccountError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def clean_memory(raw: dict) -> dict:
    """Keep only the fields the planner uses, validated. Anything else is dropped."""
    if not isinstance(raw, dict):
        raise AccountError(422, "preferences must be a JSON object")
    out: dict = {"remember": bool(raw.get("remember", True))}
    home = raw.get("home_city")
    if isinstance(home, str) and home.strip():
        if not _PLACE.match(home.strip()):
            raise AccountError(422, "home city must be a city or town name")
        out["home_city"] = home.strip()
    prefs = raw.get("preferences")
    if isinstance(prefs, list):
        out["preferences"] = [p for p in dict.fromkeys(x for x in prefs if isinstance(x, str)) if p in PREF_WORDS][:8]
    mode = raw.get("travel_mode")
    if mode in MODES:
        out["travel_mode"] = mode
    if raw.get("pace") in ("normal", "relaxed"):
        out["pace"] = raw["pace"]
    return out


class Accounts:
    def __init__(self, store, clock: Callable[[], float] = time.time):
        self.store, self.clock = store, clock
        with store._lock:
            store._conn.executescript(ACCOUNT_TABLES)
            store._conn.commit()

    def _run(self, sql: str, args: tuple = ()) -> list:
        with self.store._lock:
            rows = self.store._conn.execute(sql, args).fetchall()
            self.store._conn.commit()
        return rows

    # -- users and sessions
    def register(self, email, password) -> dict:
        if not isinstance(email, str) or not _EMAIL.match(email.strip()):
            raise AccountError(422, "Please enter a valid email address.")
        if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
            raise AccountError(422, f"The password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters.")
        email = email.strip().lower()
        salt = secrets.token_bytes(16)
        uid = uuid.uuid4().hex
        try:
            self._run("INSERT INTO users VALUES(?,?,?,?,?)",
                      (uid, email, salt.hex(), _hash_password(password, salt), now_iso()))
        except sqlite3.IntegrityError:
            raise AccountError(409, "An account with this email already exists. Sign in instead.")
        return self._new_session(uid, email)

    def login(self, email, password) -> dict:
        wrong = AccountError(401, "Wrong email or password.")
        if not isinstance(email, str) or not isinstance(password, str) or len(password) > MAX_PASSWORD:
            raise wrong
        rows = self._run("SELECT id, email, salt, pw FROM users WHERE email=?", (email.strip().lower(),))
        if not rows:
            _hash_password(password, b"0" * 16)                # same work either way: don't reveal who exists
            raise wrong
        uid, mail, salt, stored = rows[0]
        if not hmac.compare_digest(_hash_password(password, bytes.fromhex(salt)), stored):
            raise wrong
        return self._new_session(uid, mail)

    def _new_session(self, uid: str, email: str) -> dict:
        token = secrets.token_urlsafe(32)
        self._run("DELETE FROM sessions WHERE expires<?", (self.clock(),))
        self._run("INSERT INTO sessions VALUES(?,?,?)", (_hash_token(token), uid, self.clock() + SESSION_SECONDS))
        return {"token": token, "user": {"id": uid, "email": email}}

    def user_for(self, token: str | None) -> dict | None:
        if not token:
            return None
        rows = self._run("SELECT u.id, u.email FROM sessions s JOIN users u ON u.id=s.user_id "
                         "WHERE s.token_hash=? AND s.expires>=?", (_hash_token(token), self.clock()))
        return {"id": rows[0][0], "email": rows[0][1]} if rows else None

    def logout(self, token: str | None) -> None:
        if token:
            self._run("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))

    def delete_user(self, uid: str, delete_trip: Callable[[str], None]) -> None:
        """Remove the account, its sessions, saved preferences, trip list and saved trips (``delete_trip``).
        An empty marker keeps each old trip id closed to everyone, in case a copy survives somewhere."""
        for thread_id, in self._run("SELECT thread_id FROM user_trips WHERE user_id=?", (uid,)):
            delete_trip(thread_id)
            self._run("UPDATE user_trips SET user_id=?, summary='{}' WHERE thread_id=?", (DELETED, thread_id))
        for table, column in (("user_memory", "user_id"), ("sessions", "user_id"), ("users", "id")):
            self._run(f"DELETE FROM {table} WHERE {column}=?", (uid,))

    # -- memory
    def memory(self, uid: str) -> dict:
        rows = self._run("SELECT data FROM user_memory WHERE user_id=?", (uid,))
        return json.loads(rows[0][0]) if rows else {"remember": True}

    def save_memory(self, uid: str, data: dict) -> dict:
        clean = clean_memory(data)
        self._run("INSERT OR REPLACE INTO user_memory VALUES(?,?,?)", (uid, json.dumps(clean), now_iso()))
        return clean

    def forget(self, uid: str) -> dict:
        """Erase everything remembered, and stop learning until the user switches it back on."""
        return self.save_memory(uid, {"remember": False})

    def learn_from_booking(self, uid: str, constraints: dict) -> None:
        """After an approved booking, remember how this person likes to travel (never the budget)."""
        mem = self.memory(uid)
        if not mem.get("remember", True):
            return
        geo = constraints.get("origin_geo") or {}
        if geo.get("name") and _PLACE.match(geo["name"]):
            mem["home_city"] = geo["name"]
        if constraints.get("preferences"):
            mem["preferences"] = list(dict.fromkeys(constraints["preferences"] + mem.get("preferences", [])))[:8]
        if constraints.get("travel_mode") in MODES:
            mem["travel_mode"] = constraints["travel_mode"]
        mem["pace"] = constraints.get("pace", "normal")
        self.save_memory(uid, mem)

    # -- trips
    def owner(self, thread_id: str) -> str | None:
        rows = self._run("SELECT user_id FROM user_trips WHERE thread_id=?", (thread_id,))
        return rows[0][0] if rows else None

    def record_trip(self, uid: str, thread_id: str, summary: dict) -> None:
        self._run("INSERT OR REPLACE INTO user_trips VALUES(?,?,?,?)",
                  (thread_id, uid, json.dumps(summary), now_iso()))

    def trips(self, uid: str) -> list[dict]:
        rows = self._run("SELECT thread_id, summary, updated FROM user_trips WHERE user_id=? "
                         "ORDER BY updated DESC LIMIT ?", (uid, MAX_TRIPS_LISTED))
        return [{"thread_id": t, "updated": u, **json.loads(s)} for t, s, u in rows]
