"""Collects one request's records and writes them when the request ends.

A *run* is one request (plan, approve, chat, voice, ...). Inside it, *spans* are timed steps (an agent, a tool call,
a data lookup, an AI call) and *events* are moments (a safety decision, a log line). Spans nest: a lookup made by a
tool that an agent called is recorded under that tool.

The current run is carried in a context variable. Plain thread pools do not copy it, so work handed to another
thread is wrapped with ``carry``. As a second safety net, an agent can find its run by the trip's id.

Rules: outside a run every function here does nothing (so the emergency and toolkit requests, which start no run,
leave no trace); recording errors are swallowed; errors from the recorded code pass through unchanged.
"""
from __future__ import annotations

import contextvars
import functools
import os
import socket
import threading
import time
import uuid
from contextlib import contextmanager

from app.observability import privacy, settings
from app.observability.store import RecordStore, now

PRUNE_EVERY = 3600.0
MAX_SPANS_PER_RUN = 1500
_PREVIEW_ITEMS = 15

_current: contextvars.ContextVar = contextvars.ContextVar("observability_current", default=None)
_by_thread: dict[str, list] = {}                       # trip id -> runs in progress (innermost last)
_registry_lock = threading.Lock()


class _Run:
    def __init__(self, recorder, kind: str, parent_id: str | None, details: bool):
        self.recorder, self.details_on = recorder, details
        self.id = uuid.uuid4().hex
        self.t0 = time.perf_counter()
        self.row = {"id": self.id, "parent_id": parent_id, "kind": kind, "thread_id": None, "owner": None,
                    "status": None, "engine": "", "started": now().isoformat(timespec="milliseconds"),
                    "duration_ms": None, "attrs": {}}
        self.spans: list = []
        self.details: list = []
        self.hide: set = set()
        self.outer: "_Run | None" = None
        self.private = False                           # True: keep no detailed text at all for this request
        self.closed = False
        self.lock = threading.Lock()

    def offset(self, moment: float) -> float:
        return round((moment - self.t0) * 1000, 2)


class Handle:
    """One span while it is open. Safe to call when nothing is being recorded."""

    def __init__(self, run: _Run | None, type_: str = "", name: str = "", parent_id: str | None = None):
        self.run, self.type, self.name, self.parent_id = run, type_, name, parent_id
        self.id = uuid.uuid4().hex[:16] if run else None
        self.attrs: dict = {}
        self.status = "ok"
        self.t0 = time.perf_counter()
        self._texts: list = []

    def set(self, **attrs) -> None:
        if self.run:
            self.attrs.update(attrs)

    def add(self, key: str, amount: int = 1) -> None:
        if self.run:
            self.attrs[key] = self.attrs.get(key, 0) + amount

    def fail(self, status: str = "error", **attrs) -> None:
        if self.run:
            self.status = status
            self.attrs.update(attrs)

    def problem(self, error: BaseException) -> None:
        """An error the code is about to swallow: keep its kind (and, in detail, its message)."""
        if not self.run:
            return
        timed_out = isinstance(error, (TimeoutError, socket.timeout)) or "timed out" in str(error).lower()
        self.status = "timeout" if timed_out else "error"
        self.attrs["error"] = privacy.code(type(error).__name__)
        http = getattr(error, "code", None)
        if isinstance(http, int):
            self.attrs["http_status"] = http
        self.detail("error", f"{type(error).__name__}: {error}")

    def detail(self, name: str, content) -> None:
        if self.run and self.run.details_on:
            self._texts.append((name, content))


_NOTHING = Handle(None)


def current_span() -> Handle:
    here = _current.get()
    return here[1] if here and here[1] is not None else _NOTHING


def active() -> bool:
    return _current.get() is not None


def details_on() -> bool:
    here = _current.get()
    return bool(here and here[0].details_on and not here[0].private)


def _row(handle: Handle, end: float, late: bool) -> dict:
    run = handle.run
    attrs = privacy.safe_attrs(handle.attrs)
    if late:
        attrs["finished_after_request"] = True
    return {"id": handle.id, "run_id": run.id, "parent_id": handle.parent_id, "type": privacy.code(handle.type),
            "name": privacy.code(handle.name, "unnamed"), "start_ms": run.offset(handle.t0),
            "duration_ms": round((end - handle.t0) * 1000, 2), "status": privacy.code(handle.status, "ok"),
            "attrs": attrs}


def _detail_rows(run: _Run, span_id: str | None, texts: list) -> list:
    if run.private or not run.details_on:
        return []
    return [{"run_id": run.id, "span_id": span_id, "name": privacy.code(n), "content": t} for n, t in texts]


def _finish_span(handle: Handle) -> None:
    run = handle.run
    end = time.perf_counter()
    try:
        with run.lock:
            late = run.closed
            if not late:
                if len(run.spans) < MAX_SPANS_PER_RUN:
                    run.spans.append(_row(handle, end, False))
                    run.details.extend((handle.id, n, t) for n, t in handle._texts)
                else:
                    run.row["attrs"]["spans_dropped"] = run.row["attrs"].get("spans_dropped", 0) + 1
        if late:                      # a slow lookup that was left running in the background
            texts = [(n, privacy.clean_detail(t, run.hide)) for n, t in handle._texts]
            run.recorder.store.write(spans=[_row(handle, end, True)], details=_detail_rows(run, handle.id, texts))
    except Exception:                                    # noqa: BLE001 - recording must never break anything
        run.recorder.errors += 1


@contextmanager
def span(type_: str, name: str, **attrs):
    """Time a step. Exceptions are noted and passed on."""
    here = _current.get()
    if here is None:
        yield _NOTHING
        return
    run, parent = here
    handle = Handle(run, type_, name, parent.id if parent else None)
    handle.attrs.update(attrs)
    token = _current.set((run, handle))
    try:
        yield handle
    except BaseException as e:
        if handle.status == "ok":
            handle.problem(e)
        raise
    finally:
        _current.reset(token)
        _finish_span(handle)


def event(type_: str, name: str, status: str = "ok", detail=None, **attrs) -> None:
    """A moment worth recording, such as a safety decision."""
    here = _current.get()
    if here is None:
        return
    run, parent = here
    handle = Handle(run, type_, name, parent.id if parent else None)
    handle.status, handle.attrs = status, attrs
    if detail is not None:
        handle.detail("text", detail)
    _finish_span(handle)


def run_detail(name: str, content) -> None:
    """Detailed text about the whole request (kept only when RECORD_DETAILS=1)."""
    here = _current.get()
    if here and here[0].details_on and content:
        with here[0].lock:
            here[0].details.append((None, name, content))


def hide(*words) -> None:
    """Words that must never appear in this request's detailed text (names, saved preferences)."""
    here = _current.get()
    if here:
        here[0].hide.update(str(w) for w in words if w)


def private_request() -> None:
    """Keep no detailed text for this request (for example, a question about an emergency)."""
    here = _current.get()
    if here:
        here[0].private = True


def set_run(**fields) -> None:
    """status / thread_id / owner / engine of the current request; anything else becomes a basic attribute."""
    here = _current.get()
    if not here:
        return
    run = here[0]
    for key, value in fields.items():
        if key in ("status", "thread_id", "owner", "engine"):
            run.row[key] = value
            if key == "thread_id" and value:
                _register(run, value)
        else:
            run.row["attrs"][key] = value


def run_value(key: str, default=None):
    """Something noted earlier in this request with ``keep``."""
    here = _current.get()
    return getattr(here[0], "kept", {}).get(key, default) if here else default


def keep(key: str, value) -> None:
    """Remember a value until the request ends (it is not written anywhere)."""
    here = _current.get()
    if here:
        with here[0].lock:
            here[0].__dict__.setdefault("kept", {})[key] = value


def _register(run: _Run, thread_id: str) -> None:
    with _registry_lock:
        runs = _by_thread.setdefault(thread_id, [])
        if run not in runs:
            runs.append(run)


def _unregister(run: _Run) -> None:
    with _registry_lock:
        for key in [k for k, v in _by_thread.items() if run in v]:
            _by_thread[key].remove(run)
            if not _by_thread[key]:
                del _by_thread[key]


@contextmanager
def adopt(thread_id: str | None):
    """Join the run of this trip if the current thread has lost it (an engine that did not copy the context)."""
    token = None
    if _current.get() is None and thread_id:
        with _registry_lock:
            runs = _by_thread.get(thread_id)
            run = runs[-1] if runs else None
        if run is not None:
            token = _current.set((run, None))
    try:
        yield
    finally:
        if token is not None:
            _current.reset(token)


def carry(fn):
    """``fn``, bound to the current run so that it can be handed to another thread."""
    here = _current.get()
    if here is None:
        return fn

    @functools.wraps(fn)
    def bound(*args, **kwargs):
        token = _current.set(here)
        try:
            return fn(*args, **kwargs)
        finally:
            _current.reset(token)
    return bound


def _preview(result) -> list:
    """The first names or texts of what a lookup returned, for the detailed record."""
    items = result if isinstance(result, (list, tuple)) else [result]
    out = []
    for item in list(items)[:_PREVIEW_ITEMS]:
        if isinstance(item, dict):
            tags = item.get("tags") if isinstance(item.get("tags"), dict) else {}
            item = item.get("name") or item.get("text") or tags.get("name") or item
        out.append(str(item)[:300])
    return out


def _count(result) -> int:
    if result is None:
        return 0
    if isinstance(result, (list, dict, tuple, str)):
        return len(result)
    return 1


def retrieval(name: str, count=None):
    """Decorator for a data lookup: its time, how much it found, cache use and any error it swallowed.
    Statuses: ok, empty (worked, found nothing), error, timeout, skipped."""
    def decorate(fn):
        @functools.wraps(fn)
        def timed(*args, **kwargs):
            if _current.get() is None:
                return fn(*args, **kwargs)
            with span("retrieval", name) as s:
                result = fn(*args, **kwargs)
                try:
                    found = (count or _count)(result)
                    s.set(results=found)
                    if found == 0 and s.status == "ok":
                        s.status = "empty"
                    if found and s.run and s.run.details_on:
                        s.detail("results", _preview(result))
                except Exception:                        # noqa: BLE001
                    pass
                return result
        return timed
    return decorate


def note_cache(hit: bool, where: str = "disk") -> None:
    """Called by the caches: marks the lookup in progress."""
    handle = current_span()
    if handle.run and handle.type == "retrieval":
        handle.add(f"{where}_cache_hits" if hit else f"{where}_cache_misses")


def problem(error: BaseException) -> None:
    current_span().problem(error)


class Recorder:
    def __init__(self, store: RecordStore, details: bool = False, keep_days: int = 30, detail_keep_days: int = 7,
                 prune: bool = True):
        self.store, self.details = store, details
        self.keep_days, self.detail_keep_days = keep_days, detail_keep_days
        self.errors = 0                                  # records that could not be written
        self._pruned = None
        if prune:
            self.prune()

    @classmethod
    def from_env(cls) -> "Recorder | None":
        """None when recording is off or the database cannot be opened."""
        if not settings.enabled():
            old = cls.existing()
            if old is not None:                          # off now, but older records still expire
                old.prune()
            return None
        return cls._open(settings.details_enabled())

    @classmethod
    def existing(cls) -> "Recorder | None":
        """Records written earlier, even if recording is now off; None when there are none."""
        if not os.path.exists(settings.db_path()):
            return None
        return cls._open(False)

    @classmethod
    def _open(cls, details: bool) -> "Recorder | None":
        try:
            recorder = cls(RecordStore(settings.db_path()), details, settings.keep_days(),
                           settings.detail_keep_days(), prune=False)
            if settings.enabled():
                recorder.prune()
            return recorder
        except Exception as e:                           # noqa: BLE001 - the planner works without records
            print(f"Recording is off: the records database could not be opened ({type(e).__name__}).")
            return None

    def prune(self) -> None:
        if self._pruned is not None and time.monotonic() - self._pruned < PRUNE_EVERY:
            return
        self._pruned = time.monotonic()
        try:
            self.store.prune(self.keep_days, self.detail_keep_days)
        except Exception:                                # noqa: BLE001
            self.errors += 1

    def forget(self, *, thread_id: str | None = None, owner: str | None = None) -> None:
        try:
            self.store.forget(thread_id=thread_id, owner=owner)
        except Exception:                                # noqa: BLE001
            self.errors += 1

    @contextmanager
    def run(self, kind: str):
        """Record one request. A request made inside another (a plan started from the chat) is linked to it."""
        outer = _current.get()
        try:
            run = _Run(self, kind, outer[0].id if outer else None, self.details)
            if outer:
                run.outer = outer[0]
                run.row["attrs"]["via"] = outer[0].row["kind"]
                run.hide |= outer[0].hide
        except Exception:                                # noqa: BLE001
            self.errors += 1
            yield None
            return
        token = _current.set((run, None))
        try:
            yield run
        except BaseException as e:
            status = getattr(e, "status", None)          # an ApiError says why it refused
            if isinstance(status, int) and status < 500:
                run.row["status"] = "rate_limited" if status == 429 else "refused"
            else:
                run.row["status"] = "failed"
            run.row["attrs"]["error"] = privacy.code(type(e).__name__)
            if isinstance(status, int):
                run.row["attrs"]["http_status"] = status
            run_detail("error", f"{type(e).__name__}: {e}")
            raise
        finally:
            _current.reset(token)
            self._close(run)

    def _close(self, run: _Run) -> None:
        _unregister(run)
        if run.outer is not None:
            run.outer.hide |= run.hide
        try:
            with run.lock:
                run.closed = True
                spans, texts = list(run.spans), list(run.details)
            row = dict(run.row, duration_ms=run.offset(time.perf_counter()), status=run.row["status"] or "ok")
            row["status"] = privacy.code(row["status"], "ok")
            row["engine"] = privacy.code(row["engine"])
            row["thread_id"] = privacy.code(row["thread_id"]) or None
            row["owner"] = privacy.code(row["owner"]) or None
            row["attrs"] = privacy.safe_attrs(row["attrs"])
            details = []
            if not run.private:
                for span_id, name, content in texts:
                    details.extend(_detail_rows(run, span_id, [(name, privacy.clean_detail(content, run.hide))]))
            self.store.write(row, spans, details)
            self.prune()
        except Exception:                                # noqa: BLE001
            self.errors += 1
