"""Offline test cases that need no internet and no AI: how requests are read, and what the chat says and refuses.

A case with ``known_gap`` is something the planner is known to get wrong. It is listed with its result, but it is
not counted in the pass rates and does not fail the run. If it starts passing, the report says so.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Callable

from app.core.utils import fmt_inr
from app.services import request_parser as parser
from app.services.trip_service import PlannerService

CHAT_PLAN = "Plan a 4 day trip to Goa from Delhi in December, budget 90000 for 2 by flight"


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def reading_result(case: dict, today: date) -> dict:
    c = parser.parse_request(case["text"], today)["constraints"]
    wrong = [f"{k}: expected {v}, read {c.get(k)}" for k, v in case["expect"].items() if c.get(k) != v]
    return {"id": case["id"], "group": "reading", "text": case["text"], "passed": not wrong, "failed": wrong,
            "known_gap": case.get("known_gap", "")}


def _booking_state(service: PlannerService, thread_id: str | None) -> bool:
    state = service.planner.get(thread_id) if thread_id else None
    return bool(state and (state.get("status") == "booked" or state.get("booking")))


def chat_result(case: dict, make_planner: Callable) -> dict:
    """Each case gets a fresh planner, because a chat message can change the plan."""
    planner = make_planner()
    service = PlannerService(planner, require_auth=False, recorder=None)
    approvals: list = []
    resume = planner.resume

    def watched(thread_id, decision, *args, **kwargs):
        approvals.append((decision or {}).get("action"))
        return resume(thread_id, decision, *args, **kwargs)

    planner.resume = watched
    thread_id, state = None, {}
    if not case.get("no_plan"):
        thread_id = service.plan(CHAT_PLAN)["thread_id"]
        state = planner.get(thread_id)
    answer = service.chat({"message": case["message"], "thread_id": thread_id})
    reply, expect = answer.get("reply") or "", case["expect"]
    facts = {}
    if state.get("itinerary"):
        activities = [i["name"] for i in state["itinerary"]["days"][0]["items"] if i["type"] == "activity"]
        facts = {"total": fmt_inr(state["budget_report"]["total"]), "first_activity": (activities or ["?"])[0],
                 "hotel": state["hotel"]["selected"]["label"], "first_date": state["weather"]["days"][0]["date"]}
    wrong = []
    for wanted in expect.get("contains", []):
        wanted = wanted.format(**facts)
        if wanted.lower() not in reply.lower():
            wrong.append(f"reply does not say “{wanted}”")
    if expect.get("source") and answer.get("source") != expect["source"]:
        wrong.append(f"answered by {answer.get('source')}, expected {expect['source']}")
    if expect.get("excludes_digits") and re.search(r"\d", reply):
        wrong.append("the reply contains a number")
    if expect.get("never_books"):
        made = (answer.get("result") or {}).get("thread_id")
        if "approve" in approvals or _booking_state(service, thread_id) or _booking_state(service, made):
            wrong.append("THE CHAT BOOKED OR APPROVED")
    return {"id": case["id"], "group": "chat", "text": case["message"], "passed": not wrong, "failed": wrong,
            "known_gap": case.get("known_gap", "")}


def counted(cases: list[dict]) -> tuple[int, int]:
    """(passed, total) without the known gaps."""
    mine = [c for c in cases if not c.get("known_gap")]
    return sum(c["passed"] for c in mine), len(mine)
