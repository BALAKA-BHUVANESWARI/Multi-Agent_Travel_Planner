"""Run the evaluations. From the backend folder:

    python -m evaluation.run_evaluation                       # everything that is built
    python -m evaluation.run_evaluation --agent budget        # one evaluator
    python -m evaluation.run_evaluation --deterministic-only  # leave out any AI judge (there is none yet)

Offline, no AI, a fixed date. The reports go to .runtime/evaluation/ (never committed). The exit code is 1 when
a case failed or broke.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from app.core import config
from app.evaluation.results import code_version
from evaluation import cases as datasets
from evaluation import harness, report
from evaluation.evaluators import (accommodation, activity, budget, destination, end_to_end, group, itinerary,
                                   supervisor, transport, weather)
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
              "end_to_end": ("end_to_end_cases.json", end_to_end.evaluate)}
NOT_BUILT = ("grounding", "replanning", "llm_judge")


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.run_evaluation")
    ap.add_argument("--agent", choices=sorted(EVALUATORS), help="run one evaluator only")
    ap.add_argument("--deterministic-only", action="store_true",
                    help="skip AI judge evaluations (none are built yet, so everything runs)")
    ap.add_argument("--out", help="folder for the reports (default: .runtime/evaluation)")
    args = ap.parse_args(argv)
    try:
        data = run([args.agent] if args.agent else list(EVALUATORS))
    except datasets.DatasetError as e:
        print(f"Dataset problem: {e}")
        return 2
    machine, readable = save(data, Path(args.out or config.runtime_path(None, "evaluation")))
    for title, key in (("planner", "planner"), ("evaluator self-checks", "self_check")):
        c = data["summary"][key]
        print(f"{title:<24}{c['passed']} passed, {c['failed']} failed, {c['error']} errors, "
              f"{c['not_supported']} not supported ({c['total']} cases)")
    for r in data["cases"]:
        if r["status"] in (FAILED, ERROR):
            print(f"  {r['status'].upper()} {r['id']}: {r['failures'][0] if r['failures'] else ''}"[:200])
    print(f"reports: {readable}\n         {machine}")
    return 1 if data["summary"]["all"]["failed"] or data["summary"]["all"]["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
