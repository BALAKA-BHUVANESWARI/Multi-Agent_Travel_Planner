"""Evaluation harness: multi-agent graph vs a single-agent baseline using the same tools.

    python evals/run_evals.py                 # from the backend folder: offline, deterministic; writes evals/report.md
    python evals/run_evals.py --judge         # also LLM-as-judge for preference match (needs API keys)

Also run: reading_cases.json (exact dates and phrasings) and chat_cases.json (answers, fixed replies, and that the
chat never books). Every run is saved for the dashboard's Evaluations tab (--no-history skips that).
Live AI tests are separate: evals/run_live_evals.py.

Deterministic metrics (per planned trip):
  outcome      guardrail/intake/plan outcome matches the expectation
  constraints  fraction of expected constraints parsed correctly
  budget       total <= budget, or an explicit over-budget warning is present
  dates        valid, consecutive, future dates
  overlaps     no overlapping or out-of-order items; <= 4 activities/day
  rain         no outdoor activity on a rainy day
  prices       every price traces to a tool result and totals add up
  schema       itinerary has the required structure
Baseline = ONE sequential agent, same tools, normal strategy only: no guardrails, no parallelism,
no weather swaps, no budget retry loop, no critic, no human approval.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path

os.environ["REAL_DATA"] = "0"                                  # offline + deterministic
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents.budget_agent import budget_node  # noqa: E402
from app.agents.common import WORKERS  # noqa: E402
from app.agents.intake_agent import intake_node  # noqa: E402
from app.agents.itinerary_agent import merge_node  # noqa: E402
from app.core import config  # noqa: E402
from app.database.repositories import Store  # noqa: E402
from app.evaluation import offline, results  # noqa: E402
from app.graph.deps import Deps  # noqa: E402
from app.graph.runner import Planner  # noqa: E402
from app.graph.state import apply_update, initial_state  # noqa: E402
from app.services import plan_checks as checks  # noqa: E402
from app.services.llm_service import LLMRouter  # noqa: E402
from app.tools.client import InProcessClient  # noqa: E402
from app.tools.weather_tools import get_weather  # noqa: E402

TODAY = date(2026, 11, 24)
METRICS = ["outcome", "constraints", "budget", "dates", "overlaps", "rain", "prices", "schema"]


def make_planner(latency: float = 0.0):
    tools = InProcessClient(latency=latency)
    store = Store()
    deps = Deps(tools=tools, store=store, llm=LLMRouter(env={}, store=store),
                today=TODAY, sleep=lambda s: None)
    return Planner(deps), tools


# ---------------------------------------------------------------- baseline
def baseline_plan(planner: Planner, request: str) -> dict:
    """One agent, sequential tool calls, no safeguards."""
    state = initial_state(request)
    state = apply_update(state, intake_node(state, planner.deps))
    if state["status"] != "running":
        return state
    state.update(fanout=list(WORKERS), strategy="normal")
    for w in WORKERS:                                              # sequential
        state = apply_update(state, planner.nodes[w](state, planner.deps))
    state = apply_update(state, merge_node({**state, "weather": None}, planner.deps))
    state = apply_update(state, budget_node({**state, "retries": config.MAX_AUTO_REPLANS}, planner.deps))
    state["critic_issues"] = []
    state["status"] = "awaiting_approval"
    return state


# ----------------------------------------------------------------- metrics
def _planned(state: dict) -> bool:
    return state.get("status") in ("awaiting_approval", "booked") and bool(state.get("itinerary"))


def _actual_outcome(state: dict) -> str:
    st = state.get("status")
    if st in ("blocked", "needs_info"):
        return st
    if _planned(state):
        br = state["budget_report"]
        if not br["over_budget"]:
            return "within_budget"
        return "over_budget_warned" if any("over your" in w for w in state.get("warnings", [])) else "over_budget_silent"
    return st or "unknown"


def score(state: dict, case: dict) -> dict:
    out = {"outcome": _actual_outcome(state) == case["outcome"]}
    if not _planned(state):
        return out
    c = state["constraints"]
    exp = case.get("expect", {})
    if exp:
        out["constraints"] = sum(1 for k, v in exp.items() if c.get(k) == v) / len(exp)
    br = state["budget_report"]
    out["budget"] = (not br["over_budget"]) or any("over your" in w for w in state.get("warnings", []))
    issues = checks.check_dates(state)
    out["dates"] = not [i for i in issues if i["severity"] == "blocking"]
    ov = [i for i in checks.check_itinerary(state) if i["code"] in
          ("overlap", "too_many_items", "before_arrival", "after_departure")]
    out["overlaps"] = not ov
    it = state["itinerary"]
    # judge against the REAL weather for those dates, not the itinerary's own flags
    truth = {d["date"]: d["rainy"] for d in get_weather(
        c["destination"], c["start_date"], c["days"], c["today"],
        destination_geo=c.get("destination_geo"))["days"]}
    out["rain"] = not any(x["type"] == "activity" and x.get("outdoor") and x["id"] != "generic-indoor"
                          for d in it["days"] if truth.get(d["date"]) for x in d["items"])
    out["prices"] = not checks.verify_prices_and_totals(state)
    req = {"start_date", "end_date", "nights", "days"}
    out["schema"] = req <= set(it) and all({"day", "date", "items", "kind"} <= set(d) for d in it["days"]) \
        and all({"start", "end", "name", "type"} <= set(x) for d in it["days"] for x in d["items"])
    return out


def run_suite(cases: list[dict], mode: str) -> list[dict]:
    rows = []
    for case in cases:
        planner, tools = make_planner()
        t0 = time.perf_counter()
        state = planner.start(case["text"]) if mode == "graph" else baseline_plan(planner, case["text"])
        ms = (time.perf_counter() - t0) * 1000
        row = {"id": case["id"], "mode": mode, "scores": score(state, case), "ms": ms,
               "tool_calls": len(tools.calls), "status": state.get("status"),
               "retries": state.get("retries", 0), "strategy": state.get("strategy"),
               "total": (state.get("budget_report") or {}).get("total"),
               "budget": (state.get("budget_report") or {}).get("budget"),
               "outcome": _actual_outcome(state), "state": state}
        rows.append(row)
    return rows


def aggregate(rows: list[dict]) -> dict:
    agg = {}
    for m in METRICS:
        vals = [r["scores"][m] for r in rows if m in r["scores"]]
        agg[m] = (sum(float(v) for v in vals) / len(vals), len(vals)) if vals else (None, 0)
    agg["ms"] = statistics.mean(r["ms"] for r in rows)
    agg["tool_calls"] = statistics.mean(r["tool_calls"] for r in rows)
    return agg


def pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


# ------------------------------------------------------------- LLM judge
def judge(rows: list[dict], cases: dict) -> dict | None:
    config.load_env()                                   # the .env at the top of the project
    router = LLMRouter(store=Store())
    if not router.available("activities"):
        return None
    schema = {"type": "object", "required": ["score", "reason"],
              "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 5}, "reason": {"type": "string"}}}
    res = {}
    for r in rows:
        st = r["state"]
        prefs = st.get("constraints", {}).get("preferences")
        if r["mode"] != "graph" or not prefs or not _planned(st):
            continue
        names = [x["name"] for d in st["itinerary"]["days"] for x in d["items"] if x["type"] == "activity"]
        obj = router.complete_json("activities", "Rate 1-5 how well these activities match the traveler's "
                                   "stated preferences. Be strict.", json.dumps({"preferences": prefs,
                                                                                 "activities": names}), schema)
        if obj:
            res[r["id"]] = obj
    return res


# ------------------------------------------------------------------ report
def run_extra() -> dict:
    """The request-reading and chat cases (no internet, no AI)."""
    here = Path(__file__).parent
    return {"reading": [offline.reading_result(c, TODAY) for c in offline.load_cases(here / "reading_cases.json")],
            "chat": [offline.chat_result(c, lambda: make_planner()[0])
                     for c in offline.load_cases(here / "chat_cases.json")]}


def extra_section(extra: dict) -> list[str]:
    L = ["## Request reading and chat cases", "", "| Group | Passed | Known gaps (not counted) |", "|---|---|---|"]
    for name, title in (("reading", "Exact dates and phrasings"), ("chat", "Chat replies, including never books")):
        passed, total = offline.counted(extra[name])
        L.append(f"| {title} | {passed} of {total} | {sum(bool(c['known_gap']) for c in extra[name])} |")
    gaps = [c for rows in extra.values() for c in rows if c["known_gap"]]
    if gaps:
        L += ["", "Known gaps (things the planner is known to get wrong):", ""]
        L += [f"- `{c['text']}`: " + ("now passes; remove its known_gap mark" if c["passed"] else c["known_gap"])
              for c in gaps]
    failed = [c for rows in extra.values() for c in rows if not c["passed"] and not c["known_gap"]]
    if failed:
        L += ["", "Failed:", ""] + [f"- {c['id']}: {'; '.join(c['failed'])}" for c in failed]
    return L + [""]


def history_record(g_rows, b_rows, extra: dict, judged) -> dict:
    """What the dashboard shows for one run: shares per measure and one line per case. No plan text."""
    def shares(rows):
        agg = aggregate(rows)
        return {m: {"share": agg[m][0], "cases": agg[m][1]} for m in METRICS}

    baseline = {r["id"]: r for r in b_rows}
    texts = {c["id"]: c for c in CASES}

    def failed(row):
        return [m for m, v in row["scores"].items() if float(v) < 0.999]

    cases = [{"id": r["id"], "group": "planning", "text": texts[r["id"]]["text"], "passed": not failed(r),
              "failed": failed(r), "known_gap": "", "expected": texts[r["id"]]["outcome"], "outcome": r["outcome"],
              "baseline_outcome": baseline[r["id"]]["outcome"], "baseline_passed": not failed(baseline[r["id"]]),
              "baseline_failed": failed(baseline[r["id"]])} for r in g_rows]
    cases += extra["reading"] + extra["chat"]
    groups = {}
    for name in ("planning", "reading", "chat"):
        passed, total = offline.counted([c for c in cases if c["group"] == name])
        groups[name] = {"passed": passed, "total": total}
    return {"fixed_date": str(TODAY), "metrics": {"planner": shares(g_rows), "baseline": shares(b_rows)},
            "groups": groups, "cases": cases,
            "judge_mean": statistics.mean(v["score"] for v in judged.values()) if judged else None}


def build_report(g_rows, b_rows, judged, extra: dict | None = None) -> str:
    ga, ba = aggregate(g_rows), aggregate(b_rows)
    L = ["# Evaluation report", "",
         f"{len(g_rows)} prompts, offline deterministic tools, fixed date {TODAY}. "
         "Generated by `python evals/run_evals.py`.", "",
         "## Multi-agent graph vs single-agent baseline", "",
         "| Metric | Multi-agent | Baseline (single agent) | Applies to |", "|---|---|---|---|"]
    for m in METRICS:
        L.append(f"| {m} | **{pct(ga[m][0])}** | {pct(ba[m][0])} | {ga[m][1]} / {ba[m][1]} prompts |")
    L.append(f"| mean latency (ms) | {ga['ms']:.0f} | {ba['ms']:.0f} | all |")
    L.append(f"| mean tool calls | {ga['tool_calls']:.1f} | {ba['tool_calls']:.1f} | all |")
    L += ["", "Latency here is pure compute with instant mock tools; with real network tools the parallel "
          "fan-out saves roughly the sum of the three slowest worker latencies per pass (see the concurrency test).",
          "", "## Per prompt", "",
          "| Prompt | Expected | Graph outcome | Strategy / retries | Total vs budget | Baseline outcome |",
          "|---|---|---|---|---|---|"]
    case_map = {r["id"]: r for r in b_rows}
    for r in g_rows:
        b = case_map[r["id"]]
        tb = f"{r['total']:,} / {r['budget']:,}" if r["total"] else "-"
        exp = next(c for c in CASES if c["id"] == r["id"])["outcome"]
        ok = "OK" if r["scores"]["outcome"] else "MISS"
        bok = "OK" if b["scores"]["outcome"] else "MISS"
        L.append(f"| {r['id']} | {exp} | {r['outcome']} ({ok}) | {r['strategy'] or '-'} / {r['retries']} | {tb} | "
                 f"{b['outcome']} ({bok}) |")
    if extra:
        L += [""] + extra_section(extra)[:-1]
    L += ["", "## Reading the numbers", "",
          "- **budget / outcome**: the baseline never retries cheaper options and never warns, so tight and "
          "impossible budgets end over budget with no warning.",
          "- **rain**: the baseline ignores weather; the graph swaps outdoor stops for indoor ones on rainy days.",
          "- **outcome on blocked prompts**: the baseline has no guardrail, so injection and card-number "
          "prompts are processed instead of refused.",
          "- Parsing (`constraints`) is the same rule-based code in both, so it should match."]
    if judged is None:
        L += ["", "## LLM-as-judge (preference match)", "", "Skipped: no LLM API keys configured. "
              "Run with `--judge` after setting keys in `.env`."]
    elif judged:
        L += ["", "## LLM-as-judge (preference match, 1-5)", "", "| Prompt | Score | Reason |", "|---|---|---|"]
        L += [f"| {k} | {v['score']} | {v['reason'][:120]} |" for k, v in judged.items()]
        L.append(f"\nMean: {statistics.mean(v['score'] for v in judged.values()):.2f}. "
                 "LLM judges are noisy: spot-check a few by hand (below).")
    L += ["", "## Human spot-check", "",
          "Open 3 plans and check by eye: places match the stated preferences, no day feels rushed, rainy days "
          "have indoor plans, and the money lines add up. Samples:"]
    for pid in ("goa-standard", "goa-monsoon", "goa-tight-budget"):
        r = next(x for x in g_rows if x["id"] == pid)
        L += ["", f"### {pid}", "", "```", r["state"].get("summary", "")[:2600], "```"]
    return "\n".join(L) + "\n"


CASES = json.loads((Path(__file__).parent / "prompts.json").read_text())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--out", default=str(Path(__file__).parent / "report.md"))
    ap.add_argument("--no-history", action="store_true", help="do not save this run for the dashboard")
    args = ap.parse_args()
    g_rows, b_rows = run_suite(CASES, "graph"), run_suite(CASES, "baseline")
    judged = judge(g_rows, {c["id"]: c for c in CASES}) if args.judge else None
    extra = run_extra()
    report = build_report(g_rows, b_rows, judged if args.judge else None, extra)
    Path(args.out).write_text(report, encoding="utf-8")
    ga, ba = aggregate(g_rows), aggregate(b_rows)
    print(f"{'metric':<12}{'graph':>8}{'baseline':>10}")
    for m in METRICS:
        print(f"{m:<12}{pct(ga[m][0]):>8}{pct(ba[m][0]):>10}")
    record = history_record(g_rows, b_rows, extra, judged)
    broken = []
    for name, title in (("reading", "request reading"), ("chat", "chat")):
        passed, total = offline.counted(extra[name])
        gaps = [c for c in extra[name] if c["known_gap"]]
        print(f"{title + ' cases':<24}{passed} of {total} passed" + (f"; {len(gaps)} known gaps" if gaps else ""))
        broken += [c for c in extra[name] if not c["passed"] and not c["known_gap"]]
        for c in gaps:
            if c["passed"]:
                print(f"  known gap now passes: {c['id']}")
    for c in broken:
        print(f"  FAILED {c['id']}: {'; '.join(c['failed'])}")
    print(f"report written to {args.out}")
    if not args.no_history:
        results.save("offline", record)
        print(f"run saved for the dashboard in {results.folder() / 'offline'}")
    # exit non-zero if the multi-agent graph regresses on the guarantees it exists to provide, or a case fails
    ok = all((ga[m][0] or 0) >= 0.999 for m in ("outcome", "budget", "dates", "overlaps", "rain", "prices", "schema"))
    return 0 if ok and not broken else 1


if __name__ == "__main__":
    sys.exit(main())
