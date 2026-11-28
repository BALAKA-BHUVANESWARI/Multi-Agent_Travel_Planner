"""Several live AI test runs put together: accuracy, unsupported claims, failed calls and reply times.

Pure calculations on saved results; nothing here calls an AI. Only runs that can be compared are combined: made by
this way of measuring, with the same test cases and the same code version as the newest one. Every figure comes with
the number it was worked out from, because the samples are small.
"""
from __future__ import annotations

import math
import statistics

MEASURE = 2                     # 2: blocked chat answers are kept, every call is timed (1 had neither)
ENOUGH_FOR_P90 = 10             # fewer timed calls than this: no "9 out of 10" figure
JOBS = ("reading", "ranking", "summary", "chat", "judge")
KINDS = {"rate_limited": "too many requests", "server_busy": "provider busy or broken", "timeout": "no reply in time",
         "network": "network error", "refused": "refused by the provider", "unusable": "reply could not be used"}


def times(seconds: list[float]) -> dict:
    ordered = sorted(seconds)
    if not ordered:
        return {"calls": 0, "median": None, "p90": None, "slowest": None}
    return {"calls": len(ordered), "median": round(statistics.median(ordered), 2),
            "p90": round(ordered[math.ceil(0.9 * len(ordered)) - 1], 2) if len(ordered) >= ENOUGH_FOR_P90 else None,
            "slowest": round(ordered[-1], 2)}


def call_stats(log: list[dict]) -> dict:
    """Calls made and failed, and how long the good replies took (waits and retry pauses are not part of it)."""
    failed = [c for c in log if c["result"] != "ok"]
    return {"made": len(log), "failed": len(failed),
            "kinds": {k: n for k in KINDS if (n := sum(c["result"] == k for c in failed))},
            "reply": times([c["seconds"] for c in log if c["result"] == "ok"])}


def comparable(runs: list[dict], last: int | None = None) -> tuple[list[dict], dict]:
    """(the runs to combine, newest first; how many were left out and why). ``runs`` is newest first."""
    measured = [r for r in runs if r.get("measure") == MEASURE and r.get("items")]
    same = [r for r in measured if (r.get("cases_id"), r.get("version"))
            == (measured[0].get("cases_id"), measured[0].get("version"))] if measured else []
    kept = same[:last] if last else same
    return kept, {"older_way_of_measuring": len(runs) - len(measured), "other_code_or_cases": len(measured) - len(same),
                  "beyond_the_limit_asked_for": len(same) - len(kept)}


def _judged(item: dict) -> bool:
    return bool(item.get("judge")) and "by" in item["judge"]


def _job(rows: list[tuple[str, dict]]) -> dict:
    """``rows``: (run id, item) of one job of one model."""
    tried = [(r, i) for r, i in rows if i["status"] != "not_run"]
    done = [(r, i) for r, i in tried if i["status"] in ("pass", "fail")]
    by_case: dict = {}
    for _, item in done:
        by_case.setdefault(item["case"], []).append(item["status"] == "pass")
    repeated = {case: found for case, found in by_case.items() if len(found) > 1}
    return {"tried": len(tried), "not_run": len(rows) - len(tried), "answered": len(done), "passed": sum(i["status"] == "pass" for _, i in done),
            "repeated_cases": len(repeated), "always_passed": sum(all(f) for f in repeated.values()),
            "always_failed": sum(not any(f) for f in repeated.values()),
            "changed": sorted(case for case, f in repeated.items() if any(f) and not all(f))}


def _reading(rows: list[tuple[str, dict]]) -> dict:
    per_run: dict = {}
    for run_id, item in rows:
        if item["status"] in ("pass", "fail"):
            found = per_run.setdefault(run_id, [0, 0, 0])
            for field in item["fields"].values():
                found[0] += 1
                found[1] += field["rules_result"] == "right"
                found[2] += field["ai_result"] == "right"
    fields = [f for run_id, item in rows if item["status"] in ("pass", "fail") for f in item["fields"].values()]
    shares = [ai / n for n, _, ai in per_run.values() if n]
    return {"fields": len(fields), "rules_right": sum(f["rules_result"] == "right" for f in fields),
            "ai_right": sum(f["ai_result"] == "right" for f in fields),
            "made_up": sum(f["ai_result"] == "invented" for f in fields),
            "made_up_and_refused": sum("ai_refused" in f for f in fields),
            "lowest_run": round(min(shares), 3) if shares else None,
            "highest_run": round(max(shares), 3) if shares else None}


def _claims(rows: list[tuple[str, dict]]) -> dict:
    """Summaries and chat answers: what the checks and the judge found, and what a traveller would have seen."""
    done = [i for _, i in rows if i["status"] in ("pass", "fail")]
    judged = [i for i in done if _judged(i)]
    found = [i for i in judged if i["judge"].get("unsupported")]
    return {"answers": len(done), "flagged": sum(bool(i.get("flags")) for i in done),
            "stopped": sum(not i.get("shown", True) for i in done),
            "flagged_and_shown": sum(bool(i.get("flags")) and i.get("shown", True) for i in done),
            "problem_and_shown": sum(i["status"] == "fail" and i.get("shown", True) for i in done),
            "judged": len(judged), "judged_by_itself": sum(bool(i["judge"]["itself"]) for i in judged),
            "judge_found": len(found), "judge_found_and_shown": sum(i.get("shown", True) for i in found)}


def combine(runs: list[dict], marks: dict | None = None) -> list[dict]:
    """One entry per provider and model."""
    marks = marks or {}
    models: dict = {}
    for run in runs:
        for name, found in (run.get("providers") or {}).items():
            models.setdefault((name, found.get("model", "")), []).append(run)
    out = []
    for (name, model), its in sorted(models.items()):
        rows = [(r["id"], i) for r in its for i in r["items"] if i["provider"] == name]
        log = [c for r in its for c in r.get("call_log") or [] if c["provider"] == name]
        verdicts = [marks.get(f"{r}/{i['id']}") for r, i in rows if i["status"] in ("pass", "fail")]
        out.append({
            "provider": name, "model": model, "runs": len(its), "unfinished": sum(not r.get("finished") for r in its),
            "jobs": {g: _job([x for x in rows if x[1]["group"] == g]) for g in JOBS[:-1]},
            "reading": _reading([x for x in rows if x[1]["group"] == "reading"]),
            "claims": {g: _claims([x for x in rows if x[1]["group"] == g]) for g in ("summary", "chat")},
            "calls": call_stats(log),
            "reply_by_job": {j: call_stats([c for c in log if c["job"] == j])["reply"] for j in JOBS},
            "hand": {"answers": len(verdicts), "good": verdicts.count("good"), "wrong": verdicts.count("wrong")}})
    return out


def _part(part: int, whole: int) -> str:
    return f"{part} of {whole} ({part / whole:.0%})" if whole else "no data"


def _seconds(value) -> str:
    return "—" if value is None else f"{value:g} s"


def _table(head: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head),
            *("| " + " | ".join(str(c) for c in row) + " |" for row in rows)]


def text(runs: list[dict], left_out: dict, marks: dict | None = None) -> str:
    if not runs:
        old = left_out.get("older_way_of_measuring", 0)
        return ("No run to report yet. Run: python evals/run_live_evals.py"
                + (f" ({old} older run(s) are not used: they did not keep blocked answers or time each call.)" if old
                   else ""))
    lines = ["# Live AI test results", "",
             f"{len(runs)} run(s) combined, code version {runs[0].get('version') or 'unknown'}, "
             f"from {min(r.get('started', '') for r in runs)[:16]} to {max(r.get('started', '') for r in runs)[:16]}.",
             "Left out: " + ", ".join(f"{n} ({k.replace('_', ' ')})" for k, n in left_out.items() if n) + "."
             if any(left_out.values()) else "No saved run was left out.",
             "These are a few fixed test requests, not real travellers. Small samples move a lot from run to run."]
    if len(runs) < 3:
        lines.append("**Fewer than 3 runs: this does not yet show how stable the results are.**")
    for entry in combine(runs, marks):
        r, calls = entry["reading"], entry["calls"]
        lines += ["", f"## {entry['provider']} ({entry['model']}), {entry['runs']} run(s)"
                  + (f", {entry['unfinished']} unfinished" if entry["unfinished"] else ""), "", "### Accuracy", ""]
        if r["fields"]:
            lines += [f"- Trip details read right: rules alone {_part(r['rules_right'], r['fields'])}; with the AI "
                      f"{_part(r['ai_right'], r['fields'])}. Single runs ranged from {r['lowest_run']:.0%} to "
                      f"{r['highest_run']:.0%}.",
                      f"- Details made up that the app accepted: {r['made_up']}. Values the AI proposed and the app "
                      f"did not take: {r['made_up_and_refused']}.", ""]
        else:
            lines += ["- Request reading: no data.", ""]
        lines += _table(["Job", "No problem found", "Cases answered twice or more", "Same result: passed / failed",
                         "Result changed between runs"],
                        [[g, _part(j["passed"], j["answered"]), j["repeated_cases"],
                          f"{j['always_passed']} / {j['always_failed']}", ", ".join(j["changed"]) or "none"]
                         for g, j in entry["jobs"].items()])
        lines += ["", "### Unsupported claims and other problems", ""]
        lines += _table(["", "Summaries", "Chat answers"], [
            [label, *(_part(entry["claims"][g][part], entry["claims"][g][whole]) for g in ("summary", "chat"))]
            for label, part, whole in (
                ("Flagged by the fact checks", "flagged", "answers"),
                ("Stopped by the app (not shown)", "stopped", "answers"),
                ("Flagged by the fact checks but still shown", "flagged_and_shown", "answers"),
                ("Shown with any problem found", "problem_and_shown", "answers"),
                ("AI judge found unsupported statements", "judge_found", "judged"),
                ("... and the app would have shown them", "judge_found_and_shown", "judged"))])
        itself = sum(entry["claims"][g]["judged_by_itself"] for g in ("summary", "chat"))
        lines += ["", f"The fact checks and the AI judge can both miss claims or flag true ones. Answers the model "
                      f"judged itself: {itself}.", "", "### Failures", "",
                  f"- Calls that failed: {_part(calls['failed'], calls['made'])}"
                  + (": " + ", ".join(f"{KINDS[k]} {n}" for k, n in calls["kinds"].items()) if calls["kinds"] else "")
                  + ".",
                  "- Test cases left without an answer: " + _part(
                      sum(j["tried"] - j["answered"] for j in entry["jobs"].values()),
                      sum(j["tried"] for j in entry["jobs"].values())) + " of those tried.",
                  f"- Test cases not run (call limit, daily limit or a silent provider): "
                  f"{sum(j['not_run'] for j in entry['jobs'].values())}. They count in no figure above.",
                  "", "### Reply time of successful calls (waits and retry pauses not included)", ""]
        lines += _table(["Job", "Calls", "Middle (median)", "9 in 10 within", "Slowest"], [
            [job, t["calls"], _seconds(t["median"]), _seconds(t["p90"]), _seconds(t["slowest"])]
            for job, t in [*entry["reply_by_job"].items(), ("all", calls["reply"])]])
        hand = entry["hand"]
        lines += ["", f"Your own checks: {hand['good']} good, {hand['wrong']} wrong, of {hand['answers']} answers."]
    return "\n".join(lines)
