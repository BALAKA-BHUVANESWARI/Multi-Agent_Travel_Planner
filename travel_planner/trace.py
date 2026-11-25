"""Per-run tracing: how long each agent took and what the run cost, with no extra dependencies.

* ``wrap(name, fn)`` times a node function. Both engines (the LangGraph graph and the dependency-free runner)
  register nodes through it, so the numbers have the same meaning in either.
* ``Tracer.start()`` / ``Tracer.finish()`` bracket one API request (plan or approve) and report wall time,
  per-agent time, tool calls, LLM calls, cache hits, fallbacks and estimated tokens as a small ``metrics`` dict.
* Finished runs are appended to ``traces.jsonl`` (override with ``TRACE_FILE``; set ``TRACE_FILE=off`` to disable).

Cost: every service used is a free tier, so ``cost_usd`` is always 0.0. What matters is the *token estimate*
and call counts, because those are what a free-tier limit is measured in.
Tool and LLM counters are read as before/after deltas of shared counters, so they are exact for one request at a
time and approximate when several requests overlap. Agent timings are tagged by thread id and stay exact.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

MAX_RECORDS = 2000          # node timings kept in memory (older ones are dropped)
_LLM_COUNTERS = ("calls", "cache_hits", "fallbacks", "failures")


def trace_path() -> str | None:
    value = os.environ.get("TRACE_FILE", "traces.jsonl").strip()
    return None if value.lower() in ("", "off", "0", "none") else value


class Tracer:
    def __init__(self):
        self._lock = threading.Lock()
        self._nodes: deque = deque(maxlen=MAX_RECORDS)

    # -- node timings -------------------------------------------------------------------------
    def record(self, node: str, thread_id: str | None, start: float, end: float, ok: bool) -> None:
        with self._lock:
            self._nodes.append({"node": node, "thread_id": thread_id, "start": start, "end": end, "ok": ok})

    # -- one request --------------------------------------------------------------------------
    def start(self, deps) -> dict:
        llm = getattr(deps, "llm", None)
        tools = getattr(deps, "tools", None)
        return {"t0": time.perf_counter(), "wall": time.time(),
                "tool_n": len(getattr(tools, "calls", []) or []) if hasattr(tools, "calls") else None,
                "llm": {k: llm.stats.get(k, 0) for k in _LLM_COUNTERS} if llm else {}}

    def finish(self, base: dict, deps, state: dict, kind: str, engine: str = "") -> dict:
        t1 = time.perf_counter()
        tid = state.get("thread_id")
        with self._lock:
            mine = [r for r in self._nodes if r["start"] >= base["t0"] and r["end"] <= t1 + 0.05
                    and (tid is None or r["thread_id"] in (tid, None))]
        agents: dict[str, dict] = {}
        for r in mine:
            a = agents.setdefault(r["node"], {"runs": 0, "seconds": 0.0, "failed": 0})
            a["runs"] += 1
            a["seconds"] = round(a["seconds"] + (r["end"] - r["start"]), 3)
            a["failed"] += 0 if r["ok"] else 1
        slowest = max(agents.items(), key=lambda kv: kv[1]["seconds"], default=(None, None))[0]
        metrics = {"kind": kind, "thread_id": tid, "status": state.get("status"), "engine": engine,
                   "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "duration_s": round(t1 - base["t0"], 2), "agents": agents, "slowest_agent": slowest,
                   "replans": int(state.get("retries") or 0), "revisions": int(state.get("revisions") or 0),
                   "cost_usd": 0.0}
        tools = getattr(deps, "tools", None)
        if base.get("tool_n") is not None and hasattr(tools, "calls"):
            calls = list(tools.calls)[base["tool_n"]:]
            metrics.update(tool_calls=len(calls), tool_failures=sum(1 for c in calls if not c["ok"]),
                           tool_seconds=round(sum(c["end"] - c["start"] for c in calls), 2))
        llm = getattr(deps, "llm", None)
        if llm:
            d = {k: llm.stats.get(k, 0) - base["llm"].get(k, 0) for k in _LLM_COUNTERS}
            metrics.update(llm_calls=d["calls"], llm_cache_hits=d["cache_hits"], llm_fallbacks=d["fallbacks"],
                           llm_failures=d["failures"], llm_tokens_est=int(llm.stats.get("tokens", 0)),
                           llm_provider=llm.stats.get("last_provider") if d["calls"] else None)
        return metrics

    def write(self, metrics: dict) -> None:
        """Append one line to the trace file. Never raises: tracing must not break a plan."""
        path = trace_path()
        if not path:
            return
        try:
            with self._lock, open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(metrics, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError):
            pass


def wrap(name: str, fn):
    """Time a node function ``fn(state, deps)``; records into ``deps.tracer`` when there is one."""
    def timed(state, deps):
        tracer = getattr(deps, "tracer", None)
        t0 = time.perf_counter()
        ok = False
        try:
            result = fn(state, deps)
            ok = True
            return result
        finally:
            if tracer is not None:
                tracer.record(name, (state or {}).get("thread_id"), t0, time.perf_counter(), ok)
    timed.__name__ = getattr(fn, "__name__", name)
    timed.__wrapped__ = fn
    return timed
