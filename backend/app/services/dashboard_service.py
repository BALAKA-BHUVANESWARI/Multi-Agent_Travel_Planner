"""The evaluation dashboard's requests: sign-in, the numbers for each tab, and downloads. It only reads, except for
the owner's hand checks: "real problem" / "false alarm" on a flagged fact check, and "good" / "wrong" on a live
test answer. It never runs a test.

The dashboard is off until .env has DASHBOARD=1 and a DASHBOARD_PASSWORD of at least 8 characters. Signing in gives
a temporary token that is kept in memory (a restart signs everyone out) and sent with each request. Dashboard
requests are not themselves recorded.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from datetime import datetime

from app.core.rate_limit import RateLimited, RateLimiter
from app.evaluation import results as eval_results
from app.evaluation import view as eval_view
from app.observability import analytics, reports, safety, settings
from app.observability.store import RecordStore
from app.services.trip_service import ApiError, PlannerService

SESSION_SECONDS = 12 * 3600
MAX_SESSIONS = 20
EXPORTS = ("requests", "agents", "ai_calls", "lookups", "logs", "safety_events", "fact_checks", "eval_results")
_SPAN_ID = re.compile(r"[0-9a-f]{8,32}")
MAX_EXPORT_ROWS = 20_000
LOG_LEVELS = ("", "error", "warning", "info")


def _number(query: dict, name: str, default: int, most: int) -> int:
    try:
        return min(most, max(1, int(query.get(name) or default)))
    except (TypeError, ValueError):
        raise ApiError(422, f"'{name}' must be a number") from None


class DashboardService:
    def __init__(self, planner_service: PlannerService, clock=time.monotonic):
        self.service = planner_service
        self.clock = clock
        # password guesses are limited even when the planner's own rate limits are switched off
        self.guesses = RateLimiter({"client": [(5, 60), (30, 3600)], "everyone": [(100, 3600)]}, clock=clock)
        self._sessions: dict[str, tuple[float, str]] = {}        # token hash -> (expiry, password fingerprint)
        self._lock = threading.Lock()
        self._reader: RecordStore | None = None

    # ------------------------------------------------------------ on or off
    @staticmethod
    def off_reason() -> str:
        """Why the dashboard is off, or "" when it is on."""
        if not settings.dashboard_on():
            return "off"
        if not settings.dashboard_password():
            return "no_password"
        if len(settings.dashboard_password()) < settings.MIN_PASSWORD:
            return "password_too_short"
        return ""

    def status(self) -> dict:
        reason = self.off_reason()
        return {"enabled": not reason, "reason": reason, "min_password": settings.MIN_PASSWORD}

    def _require_on(self) -> None:
        if self.off_reason():
            raise ApiError(404, "The dashboard is off.")

    # ------------------------------------------------------------ sign-in
    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def login(self, body, client: str = "") -> dict:
        self._require_on()
        password = body.get("password") if isinstance(body, dict) else None
        if not isinstance(password, str) or not 0 < len(password) <= 200:
            raise ApiError(422, "Type the dashboard password.")
        try:
            self.guesses.check("client", client or "local")
            self.guesses.check("everyone", "all")
        except RateLimited as e:
            raise ApiError(429, str(e), retry_after=e.retry_after)
        real = settings.dashboard_password()
        if not hmac.compare_digest(password.strip().encode("utf-8"), real.encode("utf-8")):
            raise ApiError(401, "That password is not right.")
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = self.clock()
            self._sessions = {k: v for k, v in self._sessions.items() if v[0] > now}
            while len(self._sessions) >= MAX_SESSIONS:
                self._sessions.pop(next(iter(self._sessions)))
            self._sessions[self._hash(token)] = (now + SESSION_SECONDS, self._hash(real))
        return {"token": token, "expires_in": SESSION_SECONDS}

    def logout(self, token: str | None) -> dict:
        with self._lock:
            self._sessions.pop(self._hash(token or ""), None)
        return {"ok": True}

    def _signed_in(self, token: str | None) -> None:
        self._require_on()
        with self._lock:
            found = self._sessions.get(self._hash(token)) if token else None
        # a changed password ends every session made with the old one
        if not found or found[0] <= self.clock() or found[1] != self._hash(settings.dashboard_password()):
            raise ApiError(401, "Please sign in to the dashboard.")

    # ------------------------------------------------------------ the records
    def _store(self) -> RecordStore | None:
        """A separate connection for reading, so that looking at the dashboard never makes a plan wait."""
        recorder = self.service.recorder
        if recorder is not None:
            recorder.prune()                                   # old records expire even on a quiet day
            if recorder.store.path == ":memory:":
                return recorder.store
        if self._reader is None:
            if recorder is not None:
                self._reader = RecordStore(recorder.store.path)
            else:                                              # recording is off: show what was recorded before
                from app.observability.recorder import Recorder
                earlier = Recorder.existing()
                if earlier is not None:
                    earlier.prune()
                    self._reader = earlier.store
        return self._reader

    def _recording(self) -> dict:
        recorder = self.service.recorder
        return {"mode": "off" if recorder is None else "detailed" if recorder.details else "basic",
                "keep_days": settings.keep_days(), "detail_keep_days": settings.detail_keep_days(),
                "write_errors": recorder.errors if recorder else 0}

    def get(self, view: str, query: dict, token: str | None = None) -> dict:
        self._signed_in(token)
        try:
            filters = analytics.parse_filters(query)
        except ValueError as e:
            raise ApiError(422, str(e))
        store = self._store()
        if view == "options":
            return {**analytics.options(store), "recording": self._recording(), "engine": self.service.engine}
        if view == "evals":                                    # saved test results, not recorded requests
            return eval_view.evaluations(query)
        if view.startswith("runs/"):
            found = analytics.trace(store, view[len("runs/"):])
            if found is None:
                raise ApiError(404, "That request is not in the records (it may have expired).")
            return found
        views = ("overview", "agents", "ai", "runs", "retrieval", "logs", "guardrails", "factchecks")
        if view not in views:
            raise ApiError(404, "not found")
        data = analytics.Data.load(store, filters)
        if view == "overview":
            return {**analytics.overview(data), "limits": reports.daily_limits(self.service.planner.deps),
                    "evals": reports.eval_scores(), "recording": self._recording()}
        if view == "agents":
            return analytics.agents(data)
        if view == "ai":
            return analytics.ai(data, _number(query, "limit", 300, 2000))
        if view == "runs":
            return analytics.run_list(data, _number(query, "limit", 100, 2000))
        if view == "retrieval":
            return analytics.retrieval(data)
        if view == "guardrails":
            texts = {k: v for k, v in analytics.texts_by_step(store, data).items() if isinstance(k, str)}
            return {**safety.guardrails(data, texts), "recording": self._recording()}
        if view == "factchecks":
            only = str(query.get("show") or "")
            if only not in ("", "unmarked", *safety.VERDICTS):
                raise ApiError(422, "unknown choice")
            return {**safety.fact_checks(store, data, only), "recording": self._recording()}
        level = str(query.get("level") or "")
        if level not in LOG_LEVELS:
            raise ApiError(422, "unknown level")
        return analytics.logs(store, data, str(query.get("q") or "")[:100], level, str(query.get("type") or "")[:40],
                              _number(query, "limit", 200, 2000))

    def mark(self, body, token: str | None = None) -> dict:
        """Mark a flagged fact check as a real problem or a false alarm ("" removes the mark)."""
        self._signed_in(token)
        if not isinstance(body, dict):
            raise ApiError(422, "body must be a JSON object")
        if "eval_run" in body:
            return self._mark_answer(body)
        span_id, verdict = body.get("id"), body.get("verdict")
        if not isinstance(span_id, str) or not _SPAN_ID.fullmatch(span_id) \
                or verdict not in ("", *safety.VERDICTS):
            raise ApiError(422, f"send 'id' and 'verdict' ({', '.join(safety.VERDICTS)}, or empty)")
        store = self._store()
        if store is None or not store.set_mark(span_id, verdict):
            raise ApiError(404, "That check is not in the records (it may have expired).")
        return {"ok": True, "id": span_id, "verdict": verdict}

    @staticmethod
    def _mark_answer(body: dict) -> dict:
        run_id, item, verdict = body.get("eval_run"), body.get("item"), body.get("verdict")
        if not isinstance(run_id, str) or not isinstance(item, str) or verdict not in ("", *eval_results.VERDICTS):
            raise ApiError(422, f"send 'eval_run', 'item' and 'verdict' ({', '.join(eval_results.VERDICTS)}, or empty)")
        if not eval_results.set_mark(run_id, item, verdict):
            raise ApiError(404, "That test answer is not saved any more.")
        return {"ok": True, "item": item, "verdict": verdict}

    def export(self, query: dict, token: str | None = None) -> tuple[bytes, str, str]:
        """(file, content type, file name) for the records that match the filters."""
        self._signed_in(token)
        what, form = str(query.get("what") or ""), str(query.get("format") or "csv")
        if what not in EXPORTS or form not in ("csv", "json"):
            raise ApiError(422, f"choose 'what' from {', '.join(EXPORTS)} and 'format' csv or json")
        try:
            filters = analytics.parse_filters(query)
        except ValueError as e:
            raise ApiError(422, str(e))
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        kind = "text/csv" if form == "csv" else "application/json"
        if what == "eval_results":
            rows = eval_view.export_rows()[:MAX_EXPORT_ROWS]
            return (reports.as_csv(rows) if form == "csv" else reports.as_json(rows)), kind, \
                f"metrics-{what}-{stamp}.{form}"
        store = self._store()
        data = analytics.Data.load(store, filters)
        if what == "requests":
            rows = analytics.run_list(data, MAX_EXPORT_ROWS)["runs"]
        elif what == "agents":
            rows = analytics.agents(data)["agents"]
        elif what == "ai_calls":
            rows = analytics.ai_calls(data)
        elif what == "lookups":
            rows = analytics.lookup_rows(data)
        elif what == "safety_events":
            rows = safety.event_rows(data)
        elif what == "fact_checks":
            rows = safety.check_rows(store, data)
        else:
            level = str(query.get("level") or "")
            rows = analytics.logs(store, data, str(query.get("q") or "")[:100], level if level in LOG_LEVELS else "",
                                  str(query.get("type") or "")[:40], MAX_EXPORT_ROWS, clip=0)["entries"]
        rows = rows[:MAX_EXPORT_ROWS]
        body = reports.as_csv(rows) if form == "csv" else reports.as_json(rows)
        return body, kind, f"metrics-{what}-{stamp}.{form}"
