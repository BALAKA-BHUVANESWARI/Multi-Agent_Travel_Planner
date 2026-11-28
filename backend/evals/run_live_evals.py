"""Live AI tests. These call your AI providers with the keys in .env, so you run them yourself.

    python evals/run_live_evals.py --list                 # what would run and how many calls; calls nothing
    python evals/run_live_evals.py                        # every provider that has a key, at most 100 calls
    python evals/run_live_evals.py --providers groq       # one provider
    python evals/run_live_evals.py --only reading,chat    # some of the tests
    python evals/run_live_evals.py --no-judge             # without the AI judge
    python evals/run_live_evals.py --report               # put the saved runs together; calls nothing

At most 100 calls a run, retries and the judge included. The saved-answer cache is off, and the calls count
toward the app's daily limit per provider. Plans are built offline with a fixed date and made-up requests;
nothing about real travellers is sent. Results are saved for the dashboard's Evaluations tab.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ["REAL_DATA"] = "0"                                  # plans and places offline: only the AI is live
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import config  # noqa: E402
from app.evaluation import live, repeat, results  # noqa: E402

WORDS = {"pass": "ok", "fail": "PROBLEM", "no_answer": "no answer", "not_run": "not run", "error": "TEST ERROR"}


def show_item(item: dict) -> None:
    line = f"  {item['provider']:<7}{item['group']:<9}{item['case']:<20}{WORDS.get(item['status'], item['status'])}"
    if item.get("problems"):
        line += ": " + "; ".join(item["problems"])[:300]
    print(line, flush=True)


def show_wait(provider: str, seconds: float) -> None:
    print(f"  {provider} says too many requests: waiting {seconds:.0f} s (Ctrl+C stops and keeps what finished)",
          flush=True)


def _pct(value) -> str:
    return "—" if value is None else f"{value:.0%}"


def summary_lines(record: dict) -> list[str]:
    lines = []
    for name, found in record["providers"].items():
        g = found["groups"]
        lines.append(f"{name} ({found['model']}), {found['calls']} calls")
        r = g["reading"]
        if r["answered"]:
            lines.append(f"  reading   fields right: rules alone {r['rules_right']} of {r['fields']}, with AI "
                         f"{r['ai_right']} of {r['fields']}; made up {r['invented']}")
        r = g["ranking"]
        if r["answered"]:
            judge = "" if r["judge_ai"] is None else f"; judge (1-5): rules {r['judge_rules']}, AI {r['judge_ai']}"
            lines.append(f"  ranking   first {live.TOP} that match the preferences: rules {_pct(r['rules_share'])}, "
                         f"AI {_pct(r['ai_share'])}; ids made up {r['unknown_ids']}{judge}")
        for group, title in (("summary", "summaries"), ("chat", "chat     ")):
            r = g[group]
            if r["answered"]:
                extra = f"; {r['not_shown']} the app would not show"
                judge = f"; judge found unsupported statements in {r['judge_flagged']} of {r['judged']}" \
                    if r["judged"] else ""
                lines.append(f"  {title} {r['passed']} of {r['answered']} with no problem found; flagged by the fact "
                             f"checks {r['flagged']}{extra}{judge}")
        calls = found.get("call_stats") or {}
        if calls.get("made"):
            middle = calls["reply"]["median"]
            lines.append(f"  calls     {calls['failed']} of {calls['made']} failed"
                         + (f"; typical reply {middle:g} s" if middle is not None else ""))
        silent = sum(v["no_answer"] for v in g.values())
        skipped = sum(v["not_run"] for v in g.values())
        if silent or skipped:
            lines.append(f"  not answered {silent}, not run {skipped}")
    return lines


def write_report(last: int | None) -> int:
    found, left_out = repeat.comparable(results.runs("live"), last)
    report = repeat.text(found, left_out, results.marks())
    print(report)
    if not found:
        return 1
    path = results.folder() / "live-report.md"
    path.write_text(report + "\n", encoding="utf-8")
    print(f"\nSaved to {path}. Nothing was called.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Live AI tests (uses your API keys).")
    ap.add_argument("--list", action="store_true", help="show what would run; make no calls")
    ap.add_argument("--providers", help="comma separated: groq,gemini,ollama (default: all that are set up)")
    ap.add_argument("--only", help=f"comma separated: {','.join(live.GROUPS)}")
    ap.add_argument("--limit", type=int, default=live.MAX_CALLS, help="most calls for this run (never above 100)")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between calls")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--report", action="store_true", help="put the saved runs together; make no calls")
    ap.add_argument("--last", type=int, help="with --report: only the newest this many comparable runs")
    args = ap.parse_args()
    config.load_env()
    if args.report:
        return write_report(args.last)
    ready = live.available_providers(os.environ)
    wanted = [p.strip().lower() for p in args.providers.split(",")] if args.providers else ready
    if args.list and not wanted:
        wanted = ["groq", "gemini"]                           # --list works before any key is added
        ready = wanted
    unknown = [p for p in wanted if p not in ready]
    if unknown or not wanted:
        print("No AI provider is set up for: " + (", ".join(unknown) or "any provider")
              + ". Add the key to .env (GROQ_API_KEY or GEMINI_API_KEY).")
        return 2
    groups = tuple(g.strip() for g in args.only.split(",")) if args.only else live.GROUPS
    if any(g not in live.GROUPS for g in groups):
        print("--only takes: " + ", ".join(live.GROUPS))
        return 2
    cases = live.load_cases()
    needed = live.planned_calls({g: (cases[g] if g in groups else []) for g in live.GROUPS}, wanted,
                                not args.no_judge)
    limit = max(0, min(args.limit, live.MAX_CALLS))
    print(f"Providers: {', '.join(wanted)}. Without retries: {needed['tests']} test calls and up to "
          f"{needed['judge']} judge calls. Limit: {limit}.")
    if sum(needed.values()) > limit:
        print("That is more than the limit, so the last items (judge calls come last) will be marked 'not run'.")
    if args.list:
        for group in groups:
            print(f"\n{group}:")
            for case in cases[group]:
                print(f"  {case['id']:<20}{case['text']}")
        print("\nNothing was called.")
        return 0
    try:
        record = live.run(os.environ, providers=wanted, cases=cases, limit=limit, pause=max(0.0, args.pause),
                          judge=not args.no_judge, groups=groups, on_item=show_item, on_wait=show_wait)
    except KeyboardInterrupt:
        print("\nStopped. What had finished is saved.")
        return 130
    print()
    print("\n".join(summary_lines(record)))
    print(f"\nCalls used: {record['calls_used']} of {record['limit']}. Saved for the dashboard in "
          f"{results.folder() / 'live'}.")
    print("These tests are small: read the answers and mark them on the Evaluations tab before trusting the numbers.")
    return 0 if any(i["status"] in ("pass", "fail") for i in record["items"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
