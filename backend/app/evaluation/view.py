"""What the dashboard's Evaluations tab shows: the saved test results. These are fixed test cases, so the
dashboard's filters (which pick recorded requests) do not apply to them."""
from __future__ import annotations

from app.evaluation import results

HISTORY = 30                                      # offline runs listed
GROUP_NAMES = ("planning", "reading", "chat")


def _head(run: dict, *keys) -> dict:
    return {k: run.get(k) for k in ("id", "started", "version", *keys)}


def _counted_failures(run: dict) -> dict:
    """"group/case id" -> passed, for the cases that count."""
    return {f"{c['group']}/{c['id']}": bool(c["passed"]) for c in run.get("cases") or [] if not c.get("known_gap")}


def changes(latest: dict, before: dict | None) -> dict | None:
    """What is different from the run before: cases that started or stopped passing, and new cases."""
    if before is None:
        return None
    now, then = _counted_failures(latest), _counted_failures(before)
    return {"since": before.get("started"), "version": before.get("version"),
            "newly_failing": sorted(k for k, ok in now.items() if not ok and then.get(k) is True),
            "newly_passing": sorted(k for k, ok in now.items() if ok and then.get(k) is False),
            "new_cases": sum(k not in then for k in now), "removed_cases": sum(k not in now for k in then)}


def _offline() -> dict:
    found = results.runs("offline")
    history = [{**_head(r, "judge_mean", "groups"),
                "metrics": {side: {m: v.get("share") for m, v in (r.get("metrics", {}).get(side) or {}).items()}
                            for side in ("planner", "baseline")}} for r in found[:HISTORY]]
    return {"kept": len(found), "history": history, "latest": found[0] if found else None,
            "changes": changes(found[0], found[1] if len(found) > 1 else None) if found else None}


def _pick(found: list[dict], wanted: str) -> dict | None:
    return next((r for r in found if r.get("id") == wanted), found[0] if found else None)


def _hand_counts(run: dict, marks: dict) -> dict:
    out: dict = {}
    for item in run.get("items") or []:
        row = out.setdefault(item.get("provider", ""), {"good": 0, "wrong": 0, "answers": 0})
        if item.get("status") in ("pass", "fail"):
            row["answers"] += 1
            verdict = marks.get(f"{run['id']}/{item['id']}")
            if verdict in results.VERDICTS:
                row[verdict] += 1
    return out


def evaluations(query: dict) -> dict:
    live, voice, marks = results.runs("live"), results.runs("voice"), results.marks()
    chosen = _pick(live, str(query.get("live") or ""))
    if chosen is not None:
        chosen = {**chosen, "hand": _hand_counts(chosen, marks),
                  "items": [{**i, "mark": marks.get(f"{chosen['id']}/{i['id']}", "")}
                            for i in chosen.get("items") or []]}
    return {"offline": _offline(),
            "live": {"runs": [_head(r, "calls_used", "limit", "finished") for r in live], "chosen": chosen},
            "voice": {"runs": [{**_head(r, "finished"), "summary": r.get("summary")} for r in voice],
                      "latest": voice[0] if voice else None}}


def export_rows() -> list[dict]:
    """One row per test case, per saved run."""
    marks, rows = results.marks(), []
    for run in results.runs("offline"):
        for c in run.get("cases") or []:
            result = "passed" if c["passed"] else "failed"
            rows.append({"test": "offline", "run": run["id"], "started": run.get("started"),
                         "code_version": run.get("version"), "group": c["group"], "case": c["id"], "provider": "",
                         "text": c["text"], "result": f"known gap, {result}" if c.get("known_gap") else result,
                         "problems": "; ".join(c.get("failed") or []), "ai_answer": "", "judge": "", "hand_check": ""})
    for kind in ("live", "voice"):
        for run in results.runs(kind):
            for i in run.get("items") or []:
                judge = i.get("judge") or {}
                rows.append({"test": kind, "run": run["id"], "started": run.get("started"),
                             "code_version": run.get("version"), "group": i.get("group", "voice"),
                             "case": i.get("case", i.get("id")), "provider": i.get("provider", ""),
                             "text": i.get("text") or i.get("say", ""), "result": i.get("status"),
                             "problems": "; ".join(i.get("problems") or []), "ai_answer": i.get("answer", ""),
                             "judge": "; ".join(f"{k}={v}" for k, v in judge.items()),
                             "hand_check": marks.get(f"{run['id']}/{i['id']}", "") if kind == "live" else ""})
    return rows
