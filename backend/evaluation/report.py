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
            "estimated_cost": {"value": None, "note": "no AI calls and no prices configured"},
            "cases": rows}


def _rate(value) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _row(name: str, c: dict) -> str:
    return (f"| {name} | {c['total']} | {c[PASSED]} | {c[FAILED]} | {c[ERROR]} | {c[NOT_SUPPORTED]} | "
            f"{c[NOT_RUN]} | {_rate(c['pass_rate'])} |")


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
    lines += [f"- Tokens: {data['tokens']['note']}.", f"- Cost: {data['estimated_cost']['note']}."]
    if data.get("agents_not_built"):
        lines += ["", "## Not built yet", "", "No evaluator or cases yet (not counted above): "
                  + ", ".join(data["agents_not_built"]) + "."]
    return "\n".join(lines) + "\n"
