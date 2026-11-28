"""The numbers for the Guardrails and Hallucination checks tabs. Pure reading, like ``analytics``.

* A *safety event* is one decision by a rule: an input blocked, a card number withheld, an AI answer thrown away.
  Rules that run on every request (the input check, the plan checks) also count the times they let something pass.
* A *fact check* is one automatic comparison of what an AI returned with the plan or the typed request. "Flagged"
  means something was not found there. It is not proof of a mistake: the owner can mark each one.
"""
from __future__ import annotations

import json
import re

from app.observability.analytics import Data, _tally, at

JOBS = ("summary", "chat", "request_reading", "ranking")
AI_JOB = {"summary": "writer", "chat": "chat", "request_reading": "intake", "ranking": "activities"}
VERDICTS = ("real", "false_alarm")
WRONG_FORMAT = ("schema_invalid", "unreadable")
PRICE_CODES = ("price_untraceable", "total_mismatch")
ACTED = ("blocked", "rejected", "blocking")
MAX_LISTED = 200


def _what(span: dict) -> str:
    """The short reason of one safety event."""
    attrs, name = span["attrs"], span["name"]
    for key in ("code", "kind", "bucket", "topic", "change", "role", "field"):
        if attrs.get(key):
            return str(attrs[key])
    if name in ("writer_facts", "chat_facts"):
        return ", ".join(attrs.get("kinds") or [])
    if name == "critic_checks":
        return ", ".join(sorted(set(attrs.get("codes") or [])))
    if name == "ai_ranking_ids" and attrs.get("unknown"):
        return f"{attrs['unknown']} of {attrs.get('returned')} ids were not on the list"
    if name == "untrusted_text_cleaned":
        return f"{attrs.get('removed', 1)} phrase(s) removed"
    return ""


def guardrails(data: Data, texts: dict | None = None) -> dict:
    """``texts``: span id -> saved text (only there with detailed records)."""
    texts = texts or {}
    events: dict = {}                    # name -> [(request, step)]
    wrong_format = []
    ai_attempts = 0
    for run, s in data.each():
        if s["type"] == "guardrail":
            events.setdefault(s["name"], []).append((run, s))
        elif s["type"] == "llm_call":
            ai_attempts += 1
            if s["status"] in WRONG_FORMAT:
                wrong_format.append((run, s))

    def of(name, *statuses):
        return [(r, s) for r, s in events.get(name, []) if not statuses or s["status"] in statuses]

    def by(rows, key):
        return _tally(str(s["attrs"].get(key) or "unknown") for _, s in rows)

    inputs = of("input_check") + of("feedback_check")
    blocked = [(r, s) for r, s in inputs if s["status"] == "blocked"]
    critic = of("critic_checks")
    codes = _tally(code for _, s in critic for code in s["attrs"].get("codes") or [])
    ai_output = [
        {"check": "wrong_format", "checked": ai_attempts, "rejected": len(wrong_format)},
        {"check": "ranking_ids", "checked": len(of("ai_ranking_ids")),
         "rejected": len(of("ai_ranking_ids", "rejected"))},
        {"check": "summary_amounts", "checked": len(of("writer_amounts")),
         "rejected": len(of("writer_amounts", "rejected"))},
        {"check": "summary_facts", "checked": len(of("writer_facts")),
         "rejected": len(of("writer_facts", "rejected"))},
        {"check": "chat_facts", "checked": len(of("chat_facts")), "rejected": len(of("chat_facts", "rejected"))},
        {"check": "invented_destination", "checked": None, "rejected": len(of("ai_invented_destination"))},
        {"check": "filled_value", "checked": None, "rejected": len(of("ai_filled_value"))},
    ]
    acted = [(r, s) for r, s in data.each()
             if (s["type"] == "guardrail" and (s["status"] in ACTED or s["name"] in ("place_check",)))
             or (s["type"] == "llm_call" and s["status"] in WRONG_FORMAT)]
    recent = sorted((
        {"id": s["id"], "run_id": r["id"], "request": r["kind"], "time": at(r["started"], s["start_ms"]),
         "check": "ai_wrong_format" if s["type"] == "llm_call" else s["name"],
         "what": f"{s['name']}: {s['status'].replace('_', ' ')}" if s["type"] == "llm_call" else _what(s),
         "status": s["status"],
         # saved text is only there with detailed records; its internal label ("text: ") is not worth showing
         "text": re.sub(r"(?m)^[a-z_]+: ", "", texts.get(s["id"], ""))[:400] if s["type"] == "guardrail" else ""}
        for r, s in acted), key=lambda e: e["time"], reverse=True)
    return {
        "inputs": {"checked": len(inputs), "blocked": len(blocked), "by_reason": by(blocked, "code")},
        "private": {"typed": by(of("sensitive_data_withheld"), "kind"),
                    "spoken": by(of("spoken_sensitive_data"), "kind")},
        "web_text": {"times": len(of("untrusted_text_cleaned")),
                     "phrases": sum(s["attrs"].get("removed") or 0 for _, s in of("untrusted_text_cleaned"))},
        "ai_output": ai_output,
        "plan_checks": {"checked": len(critic),
                        "blocking": sum(s["status"] == "blocking" for _, s in critic),
                        "warnings_only": sum(s["status"] == "warnings" for _, s in critic),
                        "passed": sum(s["status"] == "ok" for _, s in critic),
                        "price_failures": sum(any(c in PRICE_CODES for c in s["attrs"].get("codes") or [])
                                              for _, s in critic),
                        "codes": codes},
        "changes": {"limit_reached": len(of("revision_limit")), "not_possible": by(of("change_not_possible"), "change"),
                    "not_understood": len(of("feedback_understood", "rejected"))},
        "rate_limits": by(of("rate_limit"), "bucket"),
        "chat_replies": by(of("chat_fixed_reply"), "topic"),
        "place_questions": len(of("place_check")),
        "acted": len(recent),
        "recent": recent[:MAX_LISTED],
    }


def _answered_by(spans: list, check: dict) -> tuple[str, str]:
    """(provider, model) of the latest AI answer for this job before the check, in the same request."""
    job = AI_JOB.get(check["name"], check["name"])
    asked = [s for s in spans if s["type"] == "llm" and s["name"] == job and s["status"] == "ok"
             and s["start_ms"] <= check["start_ms"]]
    if not asked:
        return "unknown", ""
    latest = max(asked, key=lambda s: s["start_ms"])
    if latest["attrs"].get("cache_hit"):
        return "saved answer", ""
    model = next((s["attrs"].get("model", "") for s in spans
                  if s["type"] == "llm_call" and s["parent_id"] == latest["id"] and s["status"] == "ok"), "")
    return str(latest["attrs"].get("answered_by") or "unknown"), model


def _json(text: str) -> list:
    """The saved examples. They can be cut short or cleaned, so an unreadable list is shown as nothing."""
    try:
        found = json.loads(text)
    except (ValueError, TypeError):
        return []
    return [f for f in found if isinstance(f, dict)] if isinstance(found, list) else []


def _saved(store, data: Data) -> dict:
    """span id -> {detail name: text}."""
    found: dict = {}
    if store is None:
        return found
    for d in store.details_of([r["id"] for r in data.runs]):
        if d["span_id"]:
            found.setdefault(d["span_id"], {})[d["name"]] = d["content"]
    return found


def fact_checks(store, data: Data, only: str = "") -> dict:
    """``only``: "" every flagged check, or "unmarked", "real", "false_alarm"."""
    saved = _saved(store, data)
    marks = store.marks() if store else {}
    done, errors = [], 0
    for run in data.runs:
        spans = data.spans(run["id"])
        for s in spans:
            if s["type"] != "fact_check":
                continue
            if s["status"] not in ("ok", "flagged"):
                errors += 1
                continue
            provider, model = _answered_by(spans, s)
            done.append((run, s, provider, model))
    jobs, models = [], {}
    for job in JOBS:
        mine = [(r, s) for r, s, _, _ in done if s["name"] == job]
        flagged = [s for _, s in mine if s["status"] == "flagged"]
        kinds: dict = {}
        looked: dict = {}
        for _, s in mine:
            for source, target in (("kinds", kinds), ("looked_at", looked)):
                for kind, count in (s["attrs"].get(source) or {}).items():
                    target[kind] = target.get(kind, 0) + count
        verdicts = _tally(marks.get(s["id"], "unmarked") for s in flagged)
        jobs.append({"job": job, "checked": len(mine), "flagged": len(flagged),
                     "flagged_share": round(len(flagged) / len(mine), 4) if mine else None,
                     "flagged_and_shown": sum(bool(s["attrs"].get("shown")) for s in flagged),
                     "kinds": kinds, "looked_at": looked,
                     "spelling_corrected": sum(s["attrs"].get("spelling_corrected") or 0 for _, s in mine),
                     **{v: verdicts.get(v, 0) for v in (*VERDICTS, "unmarked")}})
    for _, s, provider, model in done:
        row = models.setdefault((provider, model, s["name"]),
                                {"provider": provider, "model": model, "job": s["name"], "checked": 0, "flagged": 0})
        row["checked"] += 1
        row["flagged"] += s["status"] == "flagged"
    rows = []
    for run, s, provider, model in done:
        verdict = marks.get(s["id"], "")
        if s["status"] != "flagged" or (only and (verdict or "unmarked") != only):
            continue
        texts = saved.get(s["id"], {})
        rows.append({"id": s["id"], "run_id": run["id"], "request": run["kind"],
                     "time": at(run["started"], s["start_ms"]), "job": s["name"], "provider": provider,
                     "model": model, "shown": bool(s["attrs"].get("shown")), "count": s["attrs"].get("flags", 0),
                     "kinds": s["attrs"].get("kinds") or {}, "flags": _json(texts.get("flags", "")),
                     "ai_text": texts.get("ai_text", ""), "has_text": bool(texts), "verdict": verdict})
    rows.sort(key=lambda r: r["time"], reverse=True)
    return {"jobs": jobs, "by_model": [models[k] for k in sorted(models)], "errors": errors,
            "checked": len(done), "flagged": sum(s["status"] == "flagged" for _, s, _, _ in done),
            "items": rows[:MAX_LISTED], "items_total": len(rows)}


def event_rows(data: Data) -> list[dict]:
    """Every safety event, for the download (no saved text)."""
    rows = [{"time": at(r["started"], s["start_ms"]), "run_id": r["id"], "request": r["kind"], "check": s["name"],
             "status": s["status"], "reason": _what(s)}
            for r, s in data.each() if s["type"] == "guardrail"]
    return sorted(rows, key=lambda e: e["time"], reverse=True)


def check_rows(store, data: Data) -> list[dict]:
    """Every fact check, for the download: counts and marks, no saved text."""
    marks = store.marks() if store else {}
    rows = []
    for run in data.runs:
        spans = data.spans(run["id"])
        for s in spans:
            if s["type"] == "fact_check":
                provider, model = _answered_by(spans, s)
                rows.append({"time": at(run["started"], s["start_ms"]), "run_id": run["id"], "request": run["kind"],
                             "job": s["name"], "result": s["status"], "shown": s["attrs"].get("shown"),
                             "flags": s["attrs"].get("flags"), "kinds": s["attrs"].get("kinds"),
                             "looked_at": s["attrs"].get("looked_at"), "provider": provider, "model": model,
                             "mark": marks.get(s["id"], "")})
    return sorted(rows, key=lambda e: e["time"], reverse=True)
