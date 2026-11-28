"""Run the evaluations. From the backend folder:

    python -m evaluation.run_evaluation                       # every fixed check, plus offline speed figures
    python -m evaluation.run_evaluation --agent budget        # one evaluator
    python -m evaluation.run_evaluation --deterministic-only  # never the AI judge
    python -m evaluation.run_evaluation --records             # add speed figures from your own recorded use
    python -m evaluation.run_evaluation --prices prices.json  # work out AI cost from your prices
    python -m evaluation.run_evaluation --judge-list          # what the AI judge would do; calls nothing
    python -m evaluation.run_evaluation --judge               # also ask the AI judge (uses your AI key)

The fixed checks are offline, use no AI and a fixed date. Only --judge calls an AI. The reports go to
.runtime/evaluation/ (never committed). The exit code is 1 when a case failed or broke.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from app.core import config
from app.evaluation.results import code_version
from evaluation import cases as datasets
from evaluation import harness, judge, performance, report
from evaluation.evaluators import (accommodation, activity, budget, destination, end_to_end, grounding, group,
                                   itinerary, replanning, supervisor, transport, weather)
from evaluation.results import ERROR, FAILED, Result

# name -> (dataset file, evaluator)
EVALUATORS = {"supervisor": ("supervisor_cases.json", supervisor.evaluate),
              "destination": ("destination_cases.json", destination.evaluate),
              "transport": ("transport_cases.json", transport.evaluate),
              "accommodation": ("accommodation_cases.json", accommodation.evaluate),
              "weather": ("weather_cases.json", weather.evaluate),
              "activity": ("activity_cases.json", activity.evaluate),
              "budget": ("budget_cases.json", budget.evaluate),
              "itinerary": ("itinerary_cases.json", itinerary.evaluate),
              "group": ("group_travel_cases.json", group.evaluate),
              "end_to_end": ("end_to_end_cases.json", end_to_end.evaluate),
              "grounding": ("grounding_cases.json", grounding.evaluate),
              "replanning": ("replanning_cases.json", replanning.evaluate)}
JUDGE = "llm_judge"                     # opinions: never part of the pass rates, and only run when asked
NOT_BUILT: tuple = ()


def run_case(agent: str, case: dict, evaluate) -> dict:
    started = time.perf_counter()
    try:
        with harness.offline():
            result = evaluate(case)
    except Exception as e:                                     # noqa: BLE001 - one broken case must not end the run
        result = Result(ERROR, [f"{type(e).__name__}: {e}"])
    return {"id": case["id"], "agent": agent, "category": case["category"], "target": case["target"],
            "description": case["description"], "seconds": round(time.perf_counter() - started, 4),
            **result.as_dict()}


def run(agents: list[str], folder: Path = datasets.DATASETS) -> dict:
    rows, seen = [], set()
    for agent in agents:
        name, evaluate = EVALUATORS[agent]
        for case in datasets.load(folder / name):
            if case["id"] in seen:
                raise datasets.DatasetError(f"the id {case['id']} is used in two datasets")
            seen.add(case["id"])
            rows.append(run_case(agent, case, evaluate))
    return report.build(rows, {"timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                               "version": code_version(), "fixed_date": str(harness.TODAY), "agents": agents,
                               "agents_not_built": list(NOT_BUILT)})


def save(data: dict, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    machine, readable = out / "report.json", out / "report.md"
    machine.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    readable.write_text(report.markdown(data), encoding="utf-8")
    return machine, readable


def _waiting(provider: str, seconds: float) -> None:
    print(f"  {provider} says too many requests: waiting {seconds:.0f} s (Ctrl+C stops)", flush=True)


def _judged(row: dict) -> None:
    scores = ", ".join(f"{k.split('_')[0]} {v['score']}" for k, v in row["scores"].items())
    print(f"  judge   {row['id']:<24}{row['status']:<10}{scores or row['reason'][:120]}", flush=True)


def _settings_with_dotenv() -> dict:
    """The environment plus .env, without changing the environment: the fixed checks must not depend on your
    own settings."""
    before = dict(os.environ)
    try:
        config.load_env()
        return dict(os.environ)
    finally:
        os.environ.clear()
        os.environ.update(before)


def _list_judge(cases: list[dict], limit: int, env: dict) -> None:
    print(f"The AI judge would make {len(cases)} calls (more if one is retried). Limit: {limit}.")
    for case in cases:
        print(f"  {case['id']:<24}{case['description']}")
    try:
        provider, env = judge.settings(env)
        model = env.get(config.PROVIDERS[provider][2]) or config.PROVIDERS[provider][3]
        print(f"Judge model: {provider} {model}")
    except ValueError as e:
        print(f"Judge model: none yet ({e})")
    print("Only made-up test requests and plans built offline are sent. Nothing was called.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.run_evaluation")
    ap.add_argument("--agent", choices=sorted([*EVALUATORS, JUDGE]), help="run one evaluator only")
    ap.add_argument("--deterministic-only", action="store_true", help="only the fixed checks, never the AI judge")
    ap.add_argument("--judge", action="store_true", help="also ask the AI judge (uses your AI key)")
    ap.add_argument("--judge-list", action="store_true", help="show what the AI judge would do; calls nothing")
    ap.add_argument("--judge-limit", type=int, help="most AI calls for the judge (never above 100)")
    ap.add_argument("--records", action="store_true", help="add speed figures from your own recorded use")
    ap.add_argument("--period", choices=["today", "7d", "30d", "all"], default="all", help="used with --records")
    ap.add_argument("--prices", help="JSON file with your AI prices; without it no cost is worked out")
    ap.add_argument("--out", help="folder for the reports (default: .runtime/evaluation)")
    args = ap.parse_args(argv)
    if args.deterministic_only and (args.judge or args.agent == JUDGE):
        ap.error("--deterministic-only cannot be used with the AI judge")
    try:
        judge_cases = judge.load()
        env = _settings_with_dotenv()
        if args.judge_list:
            _list_judge(judge_cases, min(args.judge_limit if args.judge_limit is not None else 100, 100), env)
            return 0
        if args.agent == JUDGE and not args.judge:
            ap.error("the AI judge only runs with --judge (or see --judge-list)")
        if args.judge:
            judge.settings(env)                              # stop now, not after the other checks, if no key
        agents = [] if args.agent == JUDGE else [args.agent] if args.agent else list(EVALUATORS)
        data = run(agents)
        prices = performance.load_prices(args.prices or env.get("EVAL_PRICES"))
    except (datasets.DatasetError, ValueError) as e:
        print(f"{'Dataset problem' if isinstance(e, datasets.DatasetError) else 'Cannot start'}: {e}")
        return 2
    parts = {}
    if not args.agent:
        parts["offline"] = performance.offline()
    if args.records:
        parts["records"] = performance.from_records(
            args.period, config.runtime_path(env.get("OBSERVABILITY_DB"), "observability.db"))
        if parts["records"].get("ai"):
            parts["records"]["cost"] = performance.cost(parts["records"]["ai"]["models"], prices)
    data["performance"] = parts
    data["judge"] = judge.not_run(judge_cases)
    if args.judge:
        try:
            data["judge"] = judge.run(env, cases=judge_cases, limit=args.judge_limit, on_item=_judged,
                                      db=config.runtime_path(env.get("TRIP_DB"), "travel_planner.db"),
                                      on_wait=_waiting)
        except KeyboardInterrupt:
            print("\nThe judge was stopped; its results are not in the report.")
            return 130
        used = data["judge"]["tokens"]
        data["tokens"] = {"llm_calls": data["judge"]["calls_used"], "tokens_in": used["tokens_in"],
                          "tokens_out": used["tokens_out"],
                          "note": f"AI judge only: {used['tokens_in']} in, {used['tokens_out']} out"
                          + (f"; {used['calls_without_counts']} answer(s) came without token counts"
                             if used["calls_without_counts"] else "")}
        data["estimated_cost"] = performance.cost(
            [{"model": data["judge"]["model"], "tokens_in": used["tokens_in"], "tokens_out": used["tokens_out"]}],
            prices)
    out = Path(args.out or config.runtime_path(None, "evaluation"))
    if args.judge:
        kept = judge.save(data["judge"], out / "judge")      # a later run without --judge would overwrite the report
    machine, readable = save(data, out)
    if agents:
        for title, key in (("planner", "planner"), ("evaluator self-checks", "self_check")):
            c = data["summary"][key]
            print(f"{title:<24}{c['passed']} passed, {c['failed']} failed, {c['error']} errors, "
                  f"{c['not_supported']} not supported ({c['total']} cases)")
        for r in data["cases"]:
            if r["status"] in (FAILED, ERROR):
                print(f"  {r['status'].upper()} {r['id']}: {r['failures'][0] if r['failures'] else ''}"[:200])
    full = parts.get("offline", {}).get("workflow", {}).get("full_plans")
    if full and full["count"]:
        print(f"offline speed: {full['count']} full plans, median {full['median_ms']} ms, p90 {full['p90_ms']} ms "
              "(not live speed)")
    if "records" in parts:
        print(f"your records: {parts['records']['requests']} request(s) measured")
    if args.judge:
        s = data["judge"]["summary"]
        print(f"AI judge: {s['statuses']['scored']} of {s['cases']} cases scored, planted problems noticed "
              f"{s['planted_problems']['noticed']} of {s['planted_problems']['total']}; saved as {kept}")
    else:
        print(f"AI judge: not run ({len(judge_cases)} cases; see --judge-list)")
    print(f"reports: {readable}\n         {machine}")
    if args.agent == JUDGE:
        return 0 if data["judge"]["summary"]["statuses"]["scored"] else 1
    return 1 if data["summary"]["all"]["failed"] or data["summary"]["all"]["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
