"""Turns the results into the JSON report and the Markdown summary. Pure functions."""
from __future__ import annotations

import statistics

from evaluation.results import ERROR, FAILED, NOT_RUN, NOT_SUPPORTED, PASSED, STATUSES, WARN

TITLES = {"planner": "Planner (is the application right?)",
          "self_check": "Evaluator self-checks (do the checks catch planted mistakes?)"}


def counts(rows: list[dict]) -> dict:
    out = {s: sum(r["status"] == s for r in rows) for s in STATUSES}
    out["total"] = len(rows)
    judged = out[PASSED] + out[FAILED] + out[ERROR]            # not supported and not run are never counted
    out["pass_rate"] = round(out[PASSED] / judged, 4) if judged else None
    return out


def latency(rows: list[dict]) -> dict:
    times = sorted(r["seconds"] for r in rows if r.get("seconds") is not None)
    if not times:
        return {"cases": 0}
    return {"cases": len(times), "median_s": round(statistics.median(times), 4),
            "p90_s": round(times[min(len(times) - 1, int(0.9 * len(times)))], 4), "max_s": round(times[-1], 4),
            "total_s": round(sum(times), 3)}


def measures(rows: list[dict]) -> dict:
    """Per part of the planner: how many single checks were made, and the average of every measured share."""
    out = {}
    for name in sorted({r["agent"] for r in rows}):
        mine = [r for r in rows if r["agent"] == name and r["target"] == "planner"]
        shares: dict = {}
        for r in mine:
            for key, value in (r.get("measured") or {}).items():
                if key.endswith("_share"):
                    shares.setdefault(key, []).append(value)
        out[name] = {"checks_made": sum((r.get("measured") or {}).get("checks_made", 0) for r in mine),
                     "averages": {k: {"mean": round(sum(v) / len(v), 2), "cases": len(v)}
                                  for k, v in sorted(shares.items())}}
    return out


def build(rows: list[dict], meta: dict) -> dict:
    def grouped(key):
        names = sorted({r[key] for r in rows})
        return {n: {t: counts([r for r in rows if r[key] == n and r["target"] == t]) for t in TITLES} for n in names}

    return {**meta, "summary": {"all": counts(rows), **{t: counts([r for r in rows if r["target"] == t])
                                                        for t in TITLES}},
            "by_agent": grouped("agent"), "by_category": grouped("category"),
            "metrics": measures(rows),
            "latency": latency(rows),
            "tokens": {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0,
                       "note": "the deterministic evaluations make no AI calls"},
            "estimated_cost": {"value": None, "note": "not worked out: no AI tokens were used"},
            "cases": rows}


def _rate(value) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _row(name: str, c: dict) -> str:
    return (f"| {name} | {c['total']} | {c[PASSED]} | {c[FAILED]} | {c[ERROR]} | {c[NOT_SUPPORTED]} | "
            f"{c[NOT_RUN]} | {_rate(c['pass_rate'])} |")


def _ms(value) -> str:
    return "—" if value is None else f"{value:g} ms"


def _measured(value) -> str:
    return "not measured" if value is None else _rate(value)


def performance_lines(p: dict) -> list[str]:
    lines = ["", f"### Measured from {p['source']}", ""]
    if p.get("note"):
        return lines + [f"- {p['note']}"]
    w, tools, ai, ext = p["workflow"], p["tools"], p["ai"], p["external"]
    if p.get("outside_services"):
        lines.append(f"- Outside services: {p['outside_services']}.")
    for k in w["by_kind"]:
        lines.append(f"- Workflow, {k['kind']}: {k['count']} request(s), median {_ms(k['median_ms'])}, p90 "
                     f"{_ms(k['p90_ms'])}, slowest {_ms(k['max_ms'])}")
    lines += [f"- Requests: {p['requests']}; workflow failure rate {_measured(w['failure_rate'])}; automatic "
              f"re-plans {w['automatic_replans']}",
              f"- Tool calls: {tools['calls']}; failure rate {_measured(tools['failure_rate'])}; retries "
              f"{tools['retries']}",
              f"- AI: {ai['model_calls']} model call(s); failure rate {_measured(ai['failure_rate'])}; retries "
              f"{ai['retries']}; tokens in {ai['tokens_in']}, out {ai['tokens_out']}"
              + (f" ({ai['calls_with_estimated_tokens']} call(s) estimated)"
                 if ai['calls_with_estimated_tokens'] else "")
              + f"; answers from cache {_measured(ai['cache_hit_rate'])}",
              f"- Data lookups: {ext['lookups']}; failure rate {_measured(ext['failure_rate'])}; from cache "
              f"{_measured(ext['cache_hit_rate'])}; skipped {ext['skipped']}"]
    if p["agents"]:
        lines += ["", "| Agent | Runs | Median | p90 | Slowest | Succeeded | Tool calls | Tool retries | AI calls |",
                  "|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {a['agent']} | {a['runs']} | {_ms(a['median_ms'])} | {_ms(a['p90_ms'])} | "
                  f"{_ms(a['max_ms'])} | {_rate(a['success_rate'])} | {a['tool_calls']} | {a['tool_retries']} | "
                  f"{a['ai_calls']} |" for a in p["agents"]]
    if ext["sources"] and not p.get("outside_services"):
        lines += ["", "| Data source | Lookups | Errors | Timeouts | From cache | Median | p90 |",
                  "|---|---|---|---|---|---|---|"]
        lines += [f"| {s['source']} | {s['lookups']} | {s['error']} | {s['timeout']} | {s['from_cache']} | "
                  f"{_ms(s['median_ms'])} | {_ms(s['p90_ms'])} |" for s in ext["sources"]]
    if ai["models"]:
        lines += ["", "| AI job | Model | Calls | Failed | Retries | Tokens in / out | Median | p90 |",
                  "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {m['job']} | {m['provider']} {m['model']} | {m['calls']} | {m['failed']} | {m['retries']} | "
                  f"{m['tokens_in']} / {m['tokens_out']} | {_ms(m['median_ms'])} | {_ms(m['p90_ms'])} |"
                  for m in ai["models"]]
    if p.get("cost"):
        c = p["cost"]
        lines += ["", "- Cost of these AI calls: "
                  + (f"{c['value']} {c['currency']}; " if c["value"] is not None else "") + c["note"]]
    return lines


def judge_lines(j: dict) -> list[str]:
    lines = ["", "## AI judge (opinions, kept apart from every pass rate)", ""]
    if not j.get("ran"):
        return lines + [f"{j['cases_waiting']} case(s) {j['note']}"]
    s = j["summary"]
    states = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in s["statuses"].items() if n)
    lines += [f"Judge: {j['provider']} {j['model']}, run {j['timestamp']}; {j['calls_used']} of {j['limit']} calls. "
              f"Plans: {j['plans']}.", "", f"- Cases: {s['cases']} ({states})"]
    if j.get("stopped"):
        lines.append("- **The run was stopped early.** Cases marked not run were never scored.")
    planted = s["planted_problems"]
    lines.append(f"- Planted problems: noticed {planted['noticed']} of {planted['total']}, missed "
                 f"{planted['missed']}, not checked {planted['not_checked']}. A judge that misses these should not "
                 "be trusted for that quality.")
    claims = s["unsupported_claims"]
    lines.append(f"- Unsupported statements the judge listed in normal plans: {claims['listed']} "
                 f"({claims['found_in_plan']} found word for word in the plan; check each one yourself)")
    if s["averages"]:
        lines += ["", "| Quality | Average (1-5) | Cases |", "|---|---|---|"]
        lines += [f"| {k.replace('_', ' ')} | {v['mean']} | {v['cases']} |" for k, v in s["averages"].items()]
    for r in j["cases"]:
        lines += ["", f"### {r['id']} ({r['status'].replace('_', ' ')}): {r['description']}", ""]
        if r.get("reason"):
            lines.append(f"- {r['reason']}")
        lines += [f"- {k.replace('_', ' ')}: **{v['score']}** {v['reason']}" for k, v in r["scores"].items()]
        for c in r["unsupported_claims"]:
            where = "" if c["found_in_plan"] else " (these words are not in the plan)"
            lines.append(f"- Listed as unsupported: “{c['claim']}”{where}")
        if r.get("check"):
            word = {True: "Noticed", False: "MISSED", None: "Not checked"}[r["check"]["noticed"]]
            lines.append(f"- Planted problem: {word}: {r['check']['why']}")
    return lines


def markdown(data: dict) -> str:
    head = "| {} | Cases | Passed | Failed | Errors | Not supported | Not run | Pass rate |"
    rule = "|---|---|---|---|---|---|---|---|"
    lines = ["# Evaluation report", "", f"Run {data['timestamp']}; code {data['version'] or 'unknown'}; offline, "
             f"fixed date {data['fixed_date']}. Test data is synthetic.", "",
             "The pass rate is passed / (passed + failed + errors). Cases that are not supported or not run are "
             "never counted as passed.", "", "## Summary", "", head.format("What is tested"), rule]
    lines += [_row(title, data["summary"][t]) for t, title in TITLES.items()]
    lines += [_row("All cases", data["summary"]["all"])]
    for key, title in (("by_agent", "Agent"), ("by_category", "Category")):
        lines += ["", f"## By {title.lower()}", "", head.format(title), rule]
        for name, groups in data[key].items():
            lines += [_row(f"{name} ({'planner' if t == 'planner' else 'self-check'})", c)
                      for t, c in groups.items() if c["total"]]
    counted = {n: m for n, m in data.get("metrics", {}).items() if m["checks_made"] or m["averages"]}
    if counted:
        lines += ["", "## Measures (planner cases)", "", "| Agent | Single checks made | Averages |", "|---|---|---|"]
        for name, m in counted.items():
            shares = "; ".join(f"{k.replace('_', ' ')} {v['mean']:.0%} ({v['cases']} case(s))"
                               for k, v in m["averages"].items())
            lines.append(f"| {name} | {m['checks_made']} | {shares or '-'} |")
    for title, wanted in (("Failed cases", (FAILED, ERROR)), ("Not supported by the planner", (NOT_SUPPORTED,)),
                          ("Not run", (NOT_RUN,))):
        chosen = [r for r in data["cases"] if r["status"] in wanted]
        lines += ["", f"## {title}", ""]
        if not chosen:
            lines.append("None.")
        for r in chosen:
            lines.append(f"- **{r['id']}** ({r['status']}): {r['description']}")
            lines += [f"  - {reason}" for reason in r["failures"]]
    warned: dict = {}
    for r in data["cases"]:
        if r["target"] == "planner":
            for code in {f["code"] for f in r["findings"] if f["severity"] == WARN}:
                warned.setdefault(code, []).append(r["id"])
    lines += ["", "## Warnings in planner results (not failures)", ""]
    lines += [f"- {code}: {len(ids)} case(s): {', '.join(ids)}" for code, ids in sorted(warned.items())] or ["None."]
    unchecked = sorted({f["code"] for r in data["cases"] if r["target"] == "planner"
                        for f in r["findings"] if f["severity"] == "not_checked"})
    lines += ["", "Could not be checked for lack of data: " + (", ".join(unchecked) or "nothing") + "."]
    t = data["latency"]
    lines += ["", "## Time, tokens and cost", ""]
    if t["cases"]:
        lines.append(f"- Time per case: median {t['median_s']} s, p90 {t['p90_s']} s, slowest {t['max_s']} s "
                     "(offline; says nothing about live speed).")
    money = data["estimated_cost"]
    lines += [f"- Tokens: {data['tokens']['note']}.",
              "- Cost: " + (f"{money['value']} {money['currency']}; " if money.get("value") is not None else "")
              + money["note"].rstrip(".") + "."]
    for part in (data.get("performance") or {}).values():
        lines += performance_lines(part)
    if data.get("judge"):
        lines += judge_lines(data["judge"])
    if data.get("agents_not_built"):
        lines += ["", "## Not built yet", "", "No evaluator or cases yet (not counted above): "
                  + ", ".join(data["agents_not_built"]) + "."]
    return "\n".join(lines) + "\n"
