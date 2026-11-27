"""The numbers the dashboard shows, worked out from the records. Pure reading: nothing here changes anything.

Definitions used everywhere:
* a *full plan* is a plan request that reached "awaiting approval"; plan times are measured on these only, because a
  blocked request or a question back to the traveller ends after a second or two and would hide the real times;
* *median* is the middle value; *p90* is the time that 9 in 10 stayed within (interpolated between values);
* a tool answer of "not possible" (no train across the sea) is a correct answer, not a failure;
* a data lookup that found nothing ("empty") is not the same as one that failed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

ERROR_STATUSES = {"error", "failed", "timeout", "http_error", "network", "unreadable", "schema_invalid"}
WARNING_STATUSES = {"degraded", "fallback", "blocked", "rejected", "gave_up", "skipped", "rate_limited",
                    "not_possible", "refused", "warnings", "blocking", "not_configured"}
RUN_STATUSES = ("ok", "needs_info", "blocked", "refused", "rate_limited", "failed")
KINDS = ("plan", "approve", "chat", "voice", "explore", "photos", "cancel")
PERIODS = {"today": 1, "7d": 7, "30d": 30, "all": None}
AGENT_ORDER = ("guardrail", "intake", "supervisor", "flight", "hotel", "weather", "activities", "merge", "budget",
               "critic", "present", "book", "writer")
GENERIC = "generic"
_RUN_ID = re.compile(r"[0-9a-f]{32}")
_NAME = re.compile(r"[A-Za-z0-9_.:/+\-]{1,80}")
# recorded as moments, not as lookups: another source or an estimate was used instead
FALLBACK_EVENTS = {"live_prices.flights", "live_prices.hotels", "weather.offline_estimate"}


def is_lookup(span: dict) -> bool:
    return span["type"] == "retrieval" and not (span["name"] in FALLBACK_EVENTS and span["status"] == "fallback")


# ------------------------------------------------------------------ filters
@dataclass(frozen=True)
class Filters:
    period: str = "all"
    date_from: str = ""                    # YYYY-MM-DD on this computer's calendar
    date_to: str = ""
    kind: str = ""
    status: str = ""
    agent: str = ""
    model: str = ""
    run: str = ""                          # a request id or a trip id


def parse_filters(query: dict) -> Filters:
    """Check the filters in a web address. Raises ValueError with a plain reason."""
    values = {k: str(query.get(k) or "").strip() for k in Filters.__dataclass_fields__}
    values["period"] = values["period"] or "all"
    if values["period"] not in PERIODS:
        raise ValueError("unknown period")
    for key in ("date_from", "date_to"):
        if values[key]:
            try:
                date.fromisoformat(values[key])
            except ValueError:
                raise ValueError("dates must look like 2026-11-27") from None
    if values["kind"] and values["kind"] not in KINDS:
        raise ValueError("unknown request type")
    if values["status"] and values["status"] not in RUN_STATUSES:
        raise ValueError("unknown status")
    for key in ("agent", "model", "run"):
        if values[key] and not _NAME.fullmatch(values[key]):
            raise ValueError(f"unknown {key}")
    return Filters(**values)


def _utc(day: date) -> str:
    """Midnight at the start of ``day`` on this computer, as the UTC text the database stores."""
    return datetime(day.year, day.month, day.day).astimezone().astimezone(timezone.utc).isoformat(
        timespec="milliseconds")


def window(filters: Filters, today: date | None = None) -> tuple[str | None, str | None]:
    today = today or date.today()
    since = until = None
    if filters.date_from or filters.date_to:                   # chosen dates win over the period
        if filters.date_from:
            since = _utc(date.fromisoformat(filters.date_from))
        if filters.date_to:
            until = _utc(date.fromisoformat(filters.date_to) + timedelta(days=1))
    elif PERIODS[filters.period]:
        since = _utc(today - timedelta(days=PERIODS[filters.period] - 1))
    return since, until


def local_day(started: str) -> str:
    return datetime.fromisoformat(started).astimezone().date().isoformat()


def at(started: str, offset_ms: float) -> str:
    return (datetime.fromisoformat(started) + timedelta(milliseconds=offset_ms)).isoformat(timespec="milliseconds")


# ------------------------------------------------------------------ the records that match
class Data:
    """The requests that match the filters, with their steps."""

    def __init__(self, runs: list, spans: dict, filters: Filters):
        self.filters = filters
        if filters.run:
            runs = [r for r in runs if filters.run in (r["id"], r["thread_id"])]
        if filters.agent:
            runs = [r for r in runs if any(s["type"] == "agent" and s["name"] == filters.agent
                                           for s in spans.get(r["id"], []))]
        if filters.model:
            runs = [r for r in runs if any(s["type"] in ("llm_call", "voice")
                                           and s["attrs"].get("model") == filters.model
                                           for s in spans.get(r["id"], []))]
        self.runs = runs
        self.all_spans = {r["id"]: spans.get(r["id"], []) for r in runs}

    @classmethod
    def load(cls, store, filters: Filters, today: date | None = None) -> "Data":
        if store is None:
            return cls([], {}, filters)
        since, until = window(filters, today)
        runs = store.find_runs(since, until, filters.kind or None, filters.status or None)
        return cls(runs, store.spans_of([r["id"] for r in runs]), filters)

    def spans(self, run_id: str) -> list:
        """A request's steps; with an agent filter, only that agent's steps and everything under them."""
        spans = self.all_spans.get(run_id, [])
        if not self.filters.agent:
            return spans
        keep = {s["id"] for s in spans if s["type"] == "agent" and s["name"] == self.filters.agent}
        grew = True
        while grew:                                  # children can be listed before their parents finish
            more = {s["id"] for s in spans if s["parent_id"] in keep} - keep
            grew = bool(more)
            keep |= more
        return [s for s in spans if s["id"] in keep]

    def each(self):
        """(request, step) for every step in scope."""
        for run in self.runs:
            for span in self.spans(run["id"]):
                yield run, span


def percentile(values: list, share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * share
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def timing(values: list) -> dict:
    values = [v for v in values if v is not None]

    def rounded(v):
        return None if v is None else round(v, 1)

    return {"count": len(values), "median_ms": rounded(percentile(values, 0.5)),
            "p90_ms": rounded(percentile(values, 0.9)), "max_ms": rounded(max(values) if values else None)}


def _tally(items) -> dict:
    counts: dict = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def options(store) -> dict:
    """What can be picked in the filters, from everything recorded."""
    seen = store.choices() if store else {"agents": [], "models": [], "recorded": 0, "oldest": None, "newest": None}
    return {**seen, "kinds": list(KINDS), "statuses": list(RUN_STATUSES),
            "agents": sorted(seen["agents"], key=lambda a: (AGENT_ORDER.index(a) if a in AGENT_ORDER else 99, a)),
            "models": sorted(seen["models"])}


# ------------------------------------------------------------------ overview
def _replans(spans: list) -> int:
    """Automatic replans: every time the supervisor ran again within one request."""
    return max(0, sum(1 for s in spans if s["type"] == "agent" and s["name"] == "supervisor") - 1)


def overview(data: Data) -> dict:
    runs = data.runs
    plans = [r for r in runs if r["kind"] == "plan"]
    full = [r for r in plans if r["attrs"].get("outcome") == "awaiting_approval"]
    approvals = [r for r in runs if r["kind"] == "approve"]
    failed_steps = _tally(s["type"] for _, s in data.each() if s["status"] in ERROR_STATUSES)
    days: dict = {}
    for run in runs:
        row = days.setdefault(local_day(run["started"]), {k: 0 for k in RUN_STATUSES})
        row[run["status"] if run["status"] in row else "failed"] += 1
    by_kind = []
    for kind in KINDS:
        mine = [r for r in runs if r["kind"] == kind]
        if mine:
            by_kind.append({"kind": kind, "statuses": _tally(r["status"] for r in mine),
                            **timing([r["duration_ms"] for r in mine])})
    return {
        "requests": len(runs),
        "by_status": _tally(r["status"] for r in runs),
        "by_kind": by_kind,
        "engines": _tally(r["engine"] or "unknown" for r in runs),
        "plans": {"count": len(plans), "outcomes": _tally(r["attrs"].get("outcome") or r["status"] for r in plans),
                  "full": timing([r["duration_ms"] for r in full])},
        "failed_requests": sum(1 for r in runs if r["status"] == "failed"),
        "failed_steps": failed_steps,
        "replans": sum(_replans(data.spans(r["id"])) for r in runs),
        "revisions": sum(1 for r in approvals if r["attrs"].get("action") == "revise"
                         and any(s["type"] == "agent" and s["name"] == "supervisor" for s in data.spans(r["id"]))),
        "bookings": sum(1 for r in approvals
                        if r["attrs"].get("action") == "approve" and r["attrs"].get("outcome") == "booked"),
        "per_day": [{"day": day, **counts} for day, counts in sorted(days.items())][-31:],
        "recent_plans": [{"id": r["id"], "started": r["started"], "duration_ms": r["duration_ms"],
                          "days": r["attrs"].get("days"), "replans": r["attrs"].get("replans", 0)}
                         for r in reversed(full[:30])],
    }


# ------------------------------------------------------------------ agents
def _below(spans: list) -> dict:
    """span id -> every step under it."""
    children: dict = {}
    for s in spans:
        children.setdefault(s["parent_id"], []).append(s)

    def walk(span_id):
        for child in children.get(span_id, []):
            yield child
            yield from walk(child["id"])

    return {s["id"]: list(walk(s["id"])) for s in spans if s["type"] == "agent"}


def agents(data: Data) -> dict:
    rows: dict = {}
    for run in data.runs:
        spans = data.spans(run["id"])
        below = _below(spans)
        for s in spans:
            if s["type"] != "agent" or s["status"] == "not_needed":
                continue                               # a replan that did not need this agent
            row = rows.setdefault(s["name"], {"agent": s["name"], "times": [], "ok": 0, "degraded": 0, "errors": 0,
                                              "tool_calls": 0, "tool_retries": 0, "tool_errors": 0, "ai_calls": 0,
                                              "ai_retries": 0, "lookups": 0, "failed_lookups": 0})
            row["times"].append(s["duration_ms"])
            row["ok" if s["status"] == "ok" else "degraded" if s["status"] == "degraded" else "errors"] += 1
            for child in below.get(s["id"], []):
                attempt = child["attrs"].get("attempt", 1)
                if child["type"] == "tool":
                    row["tool_calls"] += 1
                    row["tool_retries"] += attempt > 1
                    row["tool_errors"] += child["status"] == "error"
                elif child["type"] == "llm_call":
                    row["ai_calls"] += 1
                    row["ai_retries"] += attempt > 1
                elif is_lookup(child):
                    row["lookups"] += 1
                    row["failed_lookups"] += child["status"] in ("error", "timeout")
    out = []
    for name in sorted(rows, key=lambda a: (AGENT_ORDER.index(a) if a in AGENT_ORDER else 99, a)):
        row = rows[name]
        times = row.pop("times")
        out.append({**row, "runs": len(times), "success_rate": round(row["ok"] / len(times), 4), **timing(times)})
    return {"agents": out}


# ------------------------------------------------------------------ AI models
def ai_calls(data: Data) -> list[dict]:
    """One row per attempt at a model, plus one for each request that never reached a model (cached, no key, or
    every provider skipped)."""
    rows = []
    for run in data.runs:
        spans = data.spans(run["id"])
        by_id = {s["id"]: s for s in spans}
        called = {s["parent_id"] for s in spans if s["type"] == "llm_call"}

        def row(span, job, provider, result, parent_attrs=None):
            attrs = span["attrs"]
            return {"run_id": run["id"], "request": run["kind"], "time": at(run["started"], span["start_ms"]),
                    "job": job, "provider": provider, "model": attrs.get("model", ""),
                    "duration_ms": span["duration_ms"], "result": result,
                    "http_status": attrs.get("http_status"),
                    "error": attrs.get("provider_code") or attrs.get("error") or attrs.get("reason") or "",
                    "attempt": attrs.get("attempt"),
                    "fallback": bool((parent_attrs or {}).get("fallback")) and result == "ok",
                    "cache_hit": bool(attrs.get("cache_hit")), "tokens_in": attrs.get("tokens_in"),
                    "tokens_out": attrs.get("tokens_out"), "tokens_estimated": attrs.get("tokens_estimated")}

        for s in spans:
            if s["type"] == "llm_call":
                parent = by_id.get(s["parent_id"])
                rows.append(row(s, parent["name"] if parent else "unknown", s["name"], s["status"],
                                parent["attrs"] if parent else None))
            elif s["type"] == "voice":
                rows.append(row(s, "voice", "groq", s["status"]))
            elif s["type"] == "llm" and s["id"] not in called:
                if s["attrs"].get("cache_hit"):
                    rows.append(row(s, s["name"], "cache", "cached"))
                else:
                    rows.append(row(s, s["name"], "none", s["status"]))
    if data.filters.model:
        rows = [r for r in rows if r["model"] == data.filters.model]
    return sorted(rows, key=lambda r: r["time"], reverse=True)


def ai(data: Data, limit: int = 300) -> dict:
    calls = ai_calls(data)
    groups: dict = {}
    for c in calls:
        if c["provider"] not in ("cache", "none"):
            groups.setdefault((c["job"], c["provider"], c["model"]), []).append(c)
    models = []
    for (job, provider, model), mine in sorted(groups.items()):
        ok = [c for c in mine if c["result"] == "ok"]
        models.append({"job": job, "provider": provider, "model": model, "calls": len(mine), "ok": len(ok),
                       "failed": len(mine) - len(ok), "retries": sum((c["attempt"] or 1) > 1 for c in mine),
                       "fallback_answers": sum(c["fallback"] for c in ok),
                       "tokens_in": sum(c["tokens_in"] or 0 for c in mine),
                       "tokens_out": sum(c["tokens_out"] or 0 for c in mine),
                       "estimated_token_calls": sum(bool(c["tokens_estimated"]) for c in mine),
                       "failures": _tally(c["result"] for c in mine if c["result"] != "ok"),
                       **timing([c["duration_ms"] for c in mine])})
    jobs: dict = {}
    for _, s in data.each():
        if s["type"] != "llm":
            continue
        job = jobs.setdefault(s["name"], {"job": s["name"], "asked": 0, "answered": 0, "from_cache": 0,
                                          "by_fallback": 0, "unanswered": 0, "no_key": 0})
        if s["status"] == "not_configured":
            job["no_key"] += 1
            continue
        job["asked"] += 1
        if s["attrs"].get("cache_hit"):
            job["from_cache"] += 1
        elif s["status"] == "ok":
            job["answered"] += 1
            job["by_fallback"] += bool(s["attrs"].get("fallback"))
        else:
            job["unanswered"] += 1
    return {"models": models, "jobs": sorted(jobs.values(), key=lambda j: j["job"]),
            "calls": calls[:limit], "total_calls": len(calls)}


# ------------------------------------------------------------------ traces
def run_summary(run: dict, spans: list) -> dict:
    return {"id": run["id"], "parent_id": run["parent_id"], "kind": run["kind"], "status": run["status"],
            "engine": run["engine"], "started": run["started"], "duration_ms": run["duration_ms"],
            "trip": run["thread_id"], "attrs": run["attrs"],
            "agents": sum(s["type"] == "agent" and s["status"] != "not_needed" for s in spans),
            "ai_calls": sum(s["type"] in ("llm_call", "voice") for s in spans),
            "lookups": sum(is_lookup(s) for s in spans),
            "failed_steps": sum(s["status"] in ERROR_STATUSES for s in spans),
            "replans": _replans(spans)}


def run_list(data: Data, limit: int = 100) -> dict:
    return {"runs": [run_summary(r, data.all_spans[r["id"]]) for r in data.runs[:limit]], "total": len(data.runs)}


def trace(store, run_id: str) -> dict | None:
    """One request as a tree of timed steps, with the requests linked to it."""
    if store is None or not _RUN_ID.fullmatch(run_id):
        return None
    run = store.run(run_id)
    if run is None:
        return None
    spans = store.spans(run_id)
    texts: dict = {}
    for d in store.details_of([run_id]):
        texts.setdefault(d["span_id"] or "", []).append({"name": d["name"], "text": d["content"]})
    ids = {s["id"] for s in spans}
    children: dict = {}
    for s in spans:
        children.setdefault(s["parent_id"] if s["parent_id"] in ids else None, []).append(s)
    ordered: list = []

    def walk(parent, depth):
        for s in sorted(children.get(parent, []), key=lambda item: item["start_ms"]):
            if s["type"] == "log":                       # the agent's note belongs to its agent
                continue
            ordered.append({"id": s["id"], "depth": depth, "type": s["type"], "name": s["name"],
                            "status": s["status"], "start_ms": s["start_ms"], "duration_ms": s["duration_ms"],
                            "attrs": s["attrs"], "texts": texts.get(s["id"], [])})
            walk(s["id"], depth + 1)

    walk(None, 0)
    shown = {s["id"]: s for s in ordered}
    for s in spans:
        if s["type"] == "log" and s["id"] in texts:
            target = shown.get(s["parent_id"])
            note = texts[s["id"]]
            if target:
                target["texts"] += [{"name": "agent note", "text": n["text"]} for n in note]
            else:
                texts.setdefault("", []).extend({"name": f"{s['name']} note", "text": n["text"]} for n in note)
    linked = store.linked_runs(run)
    linked_spans = store.spans_of([r["id"] for r in linked])
    end = max([run["duration_ms"] or 0] + [s["start_ms"] + s["duration_ms"] for s in ordered])
    return {"run": run_summary(run, spans), "steps": ordered, "texts": texts.get("", []), "timeline_ms": end,
            "has_texts": bool(texts), "linked": [run_summary(r, linked_spans[r["id"]]) for r in linked]}


# ------------------------------------------------------------------ retrieval
def _from_cache(attrs: dict) -> bool:
    hits = attrs.get("memory_cache_hits", 0) + attrs.get("disk_cache_hits", 0)
    return hits > 0 and not attrs.get("page_reads") and not attrs.get("server_attempts")


def lookup_rows(data: Data) -> list[dict]:
    rows = []
    for run, s in data.each():
        if s["type"] not in ("retrieval", "retrieval_wait"):
            continue
        kind = "gave_up_waiting" if s["type"] == "retrieval_wait" else "lookup" if is_lookup(s) else "fallback"
        rows.append({"run_id": run["id"], "request": run["kind"], "time": at(run["started"], s["start_ms"]),
                     "source": s["name"], "kind": kind, "status": s["status"], "duration_ms": s["duration_ms"],
                     "results": s["attrs"].get("results"), "from_cache": _from_cache(s["attrs"]),
                     "error": s["attrs"].get("error") or s["attrs"].get("reason") or "",
                     "http_status": s["attrs"].get("http_status")})
    return sorted(rows, key=lambda r: r["time"], reverse=True)


def retrieval(data: Data) -> dict:
    rows = lookup_rows(data)
    sources: dict = {}
    for r in rows:
        if r["kind"] == "lookup":
            sources.setdefault(r["source"], []).append(r)
    table = []
    for name, mine in sorted(sources.items()):
        statuses = _tally(r["status"] for r in mine)
        counted = [r["results"] for r in mine if isinstance(r["results"], (int, float))]
        table.append({"source": name, "lookups": len(mine),
                      **{k: statuses.get(k, 0) for k in ("ok", "empty", "error", "timeout", "skipped")},
                      "from_cache": sum(r["from_cache"] for r in mine),
                      "results_per_lookup": round(sum(counted) / len(counted), 1) if counted else None,
                      **timing([r["duration_ms"] for r in mine])})
    # which sources' places actually reached a finished plan (each version of a plan counted once)
    used: dict = {}
    prices = {"transport_price": {}, "hotel_price": {}}
    plans = 0
    for run in data.runs:
        if run["kind"] in ("plan", "approve") and run["attrs"].get("outcome") == "awaiting_approval":
            plans += 1
            for source, count in (run["attrs"].get("activity_sources") or {}).items():
                used[source] = used.get(source, 0) + count
            for key, counts in prices.items():
                value = run["attrs"].get(key)
                if value:
                    counts[value] = counts.get(value, 0) + 1
    total = sum(used.values())
    return {"sources": table,
            "fallbacks": [{"what": k, "times": v} for k, v in sorted(_tally(
                r["source"] for r in rows if r["kind"] == "fallback").items())],
            "gave_up": [{"what": k, "times": v} for k, v in sorted(_tally(
                r["source"] for r in rows if r["kind"] == "gave_up_waiting").items())],
            "in_plans": {"plans": plans, "activities": total, "by_source": used,
                         "real_share": round((total - used.get(GENERIC, 0)) / total, 4) if total else None},
            "prices": prices,
            "problems": [r for r in rows if r["status"] in ("error", "timeout", "gave_up")][:20],
            "total_lookups": sum(r["lookups"] for r in table)}


# ------------------------------------------------------------------ logs
def _level(status: str) -> str:
    return "error" if status in ERROR_STATUSES else "warning" if status in WARNING_STATUSES else "info"


def _facts(attrs: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in attrs.items() if v not in ({}, [], ""))


def log_entries(data: Data, texts: dict) -> list[dict]:
    """Every step and every request that did not succeed, newest first. ``texts``: span id or (run id) -> text."""
    entries = []
    for run in data.runs:
        if run["status"] in ("failed", "refused", "rate_limited", "blocked") and not data.filters.agent:
            entries.append({"time": at(run["started"], run["duration_ms"] or 0), "run_id": run["id"],
                            "request": run["kind"], "type": "request", "name": run["kind"], "status": run["status"],
                            "level": "error" if run["status"] == "failed" else "warning",
                            "duration_ms": run["duration_ms"], "message": _facts(run["attrs"]),
                            "text": texts.get(("run", run["id"]), "")})
        for s in data.spans(run["id"]):
            level = _level(s["status"])
            if s["type"] == "agent" and level == "info" and s["attrs"].get("warnings"):
                level = "warning"
            entries.append({"time": at(run["started"], s["start_ms"]), "run_id": run["id"], "request": run["kind"],
                            "type": s["type"], "name": s["name"], "status": s["status"], "level": level,
                            "duration_ms": s["duration_ms"], "message": _facts(s["attrs"]),
                            "text": texts.get(s["id"], "")})
    return sorted(entries, key=lambda e: e["time"], reverse=True)


def _texts_by_step(store, data: Data) -> dict:
    found: dict = {}
    if store is None:
        return found
    for d in store.details_of([r["id"] for r in data.runs]):
        key = d["span_id"] or ("run", d["run_id"])
        piece = f"{d['name']}: {d['content']}"
        found[key] = f"{found[key]}\n{piece}" if key in found else piece
    return found


def logs(store, data: Data, search: str = "", level: str = "", type_: str = "", limit: int = 200,
         clip: int = 600) -> dict:
    entries = log_entries(data, _texts_by_step(store, data))
    types = sorted({e["type"] for e in entries})
    if level:
        entries = [e for e in entries if e["level"] == level]
    if type_:
        entries = [e for e in entries if e["type"] == type_]
    if search:
        needle = search.casefold()
        entries = [e for e in entries if needle in " ".join(
            str(e[k]) for k in ("type", "name", "status", "message", "text", "request")).casefold()]
    shown = [{**e, "text": e["text"][:clip]} if clip else e for e in entries[:limit]]
    return {"entries": shown, "total": len(entries), "types": types}
