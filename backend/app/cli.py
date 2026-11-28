"""Command line interface.

    python -m app "Plan a 5 day trip to Goa from Delhi in December, budget 60k for 2"
    python -m app --auto-approve --json "..."
    python -m app            # interactive
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from app.core import config


def _ask(prompt: str) -> str | None:
    """Return the typed answer, or None when input is closed (EOF / non-interactive)."""
    try:
        return input(prompt).strip()
    except EOFError:
        return None


def run(argv: list[str] | None = None, out=sys.stdout) -> int:
    ap = argparse.ArgumentParser(prog="app", description="Multi-agent travel planner")
    ap.add_argument("request", nargs="?", help="trip request in plain language")
    ap.add_argument("--db", default=None, help="SQLite file (default: $TRIP_DB or .runtime/travel_planner.db)")
    ap.add_argument("--engine", default=None, help="auto | langgraph | runner")
    ap.add_argument("--tools", default=None, help="inprocess | mcp")
    ap.add_argument("--today", default=None, help="override today's date (YYYY-MM-DD), for demos/tests")
    ap.add_argument("--auto-approve", action="store_true", help="approve without prompting (mock booking)")
    ap.add_argument("--json", action="store_true", help="print the final state as JSON")
    ap.add_argument("--resume", metavar="THREAD_ID", help="continue a paused plan from the database")
    ap.add_argument("--log", action="store_true", help="print the agent log")
    ap.add_argument("--ask-mode", action="store_true",
                    help="ask how to travel (flight/train/bus/car/bike) when the request does not say; "
                         "otherwise say it in the request, e.g. 'by train'")
    args = ap.parse_args(argv)

    config.load_env()
    from app.services.chat_service import complete_request
    from app.services.request_parser import parse_request
    from app.graph.deps import Deps
    from app.graph.engine import make_planner
    deps = Deps.default(db=args.db, tools_mode=args.tools,
                        today=date.fromisoformat(args.today) if args.today else None,
                        ask_travel_mode=args.ask_mode)
    planner = make_planner(args.engine, deps=deps)

    def say(msg: str = "") -> None:
        print(msg, file=out)

    if args.resume:
        state = planner.get(args.resume)
        if state is None:
            say(f"No thread '{args.resume}' in {deps.store.path}")
            return 2
    else:
        text = args.request or _ask("Where would you like to go? ") or ""
        state = planner.start(text)
        for _ in range(3):                                   # follow-up questions for missing info
            if state["status"] != "needs_info" or args.auto_approve or not sys.stdin.isatty():
                break
            say(state["message"])
            more = _ask("> ")
            if not more:
                break
            wrong_date = parse_request(text, deps.today)["bad_date"]       # the new date replaces it
            text = complete_request(state, more) if state.get("place_check") or wrong_date else f"{text}. {more}"
            state = planner.start(text)

    shown = None
    while state["status"] == "awaiting_approval":
        if args.auto_approve:                       # the booked summary is printed once, below
            action, feedback = "approve", ""
        else:
            if state is not shown:                           # print each plan version once
                say(state["summary"])
                say(f"\n[thread {state['thread_id']}]  {state['message']}")
                shown = state
            choice = _ask("[a]pprove  [r]equest changes  [c]ancel > ")
            if choice is None:                               # input closed: stay paused
                say("Paused. Resume later with --resume " + state["thread_id"])
                break
            choice = choice.lower()
            if choice.startswith("r") and state["pending_approval"]["can_revise"]:
                feedback = _ask("What should change? ")
                if not feedback:
                    continue
                action = "revise"
            elif choice.startswith("r"):
                say("Revision limit reached: approve or cancel.")
                continue
            elif choice.startswith("a"):
                action, feedback = "approve", ""
            elif choice.startswith("c"):
                action, feedback = "cancel", ""
            else:
                say("Please type a (approve), r (request changes) or c (cancel).")
                continue
        state = planner.resume(state["thread_id"], {"action": action, "feedback": feedback})

    if state["status"] == "booked":
        say(state["summary"])
        say(f"\nBooked (MOCK): {state['booking']['booking_id']}")
    elif state["status"] in ("blocked", "needs_info", "cancelled"):
        say(state["message"])
    if args.log:
        say("\n--- agent log ---")
        for l in state["log"]:
            say(f"{l['t'][11:23]}  {l['agent']:<10} {l['msg']}")
    if args.json:
        say(json.dumps(state, indent=2, default=str))
    return 0 if state["status"] in ("booked", "awaiting_approval", "cancelled") else 1


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
