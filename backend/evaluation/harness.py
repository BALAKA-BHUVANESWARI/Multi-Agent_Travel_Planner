"""Runs the real planner for an evaluation case: offline data, no AI, a fixed date, nothing saved to disk."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from app.database.repositories import Store
from app.graph.deps import Deps
from app.graph.runner import Planner
from app.services import chat_service
from app.services.llm_service import LLMRouter
from app.tools.client import InProcessClient

TODAY = date(2026, 11, 24)
_OFFLINE = {"REAL_DATA": "0", "OBSERVABILITY": "0"}


class PlanNotMade(RuntimeError):
    pass


@contextmanager
def offline():
    """No internet lookups and no dashboard records while evaluating; the old settings come back afterwards."""
    before = {k: os.environ.get(k) for k in _OFFLINE}
    os.environ.update(_OFFLINE)
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class RecordingClient(InProcessClient):
    """The offline tools, keeping what each call was asked and what it answered: the "provider data" that the
    agents' results are compared with."""

    def __init__(self, failures: dict | None = None):
        super().__init__(failures=failures)
        self.log: list[tuple[str, dict, dict | None, str]] = []

    def call(self, name: str, **kwargs) -> dict:
        try:
            result = super().call(name, **kwargs)
        except Exception as e:
            self.log.append((name, _plain(kwargs), None, str(e)))
            raise
        self.log.append((name, _plain(kwargs), _plain(result), ""))
        return result


def _plain(value):
    """A copy made of plain JSON types, so that later changes to the plan cannot change what was recorded."""
    return json.loads(json.dumps(value, default=str))


FIXTURES = Path(__file__).resolve().parents[1] / "app" / "tests" / "fixtures"
# the start of each AI job's instructions, to tell which job is asking
_AI_JOBS = {"Write a friendly": "writer", "You answer": "chat", "Extract trip": "intake",
            "You re-rank": "activities"}


class PretendAI:
    """A scripted AI model: no network. ``replies``: job -> the JSON it answers with (a job that is not listed
    gets an unusable answer, so the rules take over). ``asked`` lists the jobs that really called it."""

    def __init__(self, replies: dict):
        self.replies, self.asked = replies, []

    def __call__(self, url, headers, body, timeout):
        system = body["messages"][0]["content"]
        job = next((name for start, name in _AI_JOBS.items() if system.startswith(start)), "unknown")
        self.asked.append(job)
        content = json.dumps(self.replies[job]) if job in self.replies else "no answer"
        return 200, {"choices": [{"message": {"content": content}}]}


@contextmanager
def recorded_live(settings: dict | None):
    """Switch live prices on, answered from saved real pages in ``app/tests/fixtures`` instead of the internet.
    ``settings``: {"pages": {"flights"|"hotels": file name}, "fetched_at": time}. A kind without a page behaves
    like a live lookup that failed."""
    if not settings:
        yield
        return
    from app.core import config
    from app.integrations import live_prices as live

    def page(url, ok, attempts=2):
        name = settings["pages"].get("flights" if "flights" in url else "hotels")
        if name:
            text = (FIXTURES / name).read_text(encoding="utf-8")
            if ok(text):
                return text, settings["fetched_at"], False
        raise live.LiveUnavailable("no recorded page for this search", "no_results_on_page")

    saved = (config.live_prices_enabled, live.get_page, live.rate_to_inr)
    config.live_prices_enabled = lambda: True
    live.get_page = page
    live.rate_to_inr = lambda code: (1.0, "") if code.upper() == "INR" else (88.0, "2026-11-25")
    try:
        yield
    finally:
        config.live_prices_enabled, live.get_page, live.rate_to_inr = saved


def _deps(tools, store, ai: PretendAI | None = None, ask_travel_mode: bool = False) -> Deps:
    env = {"GROQ_API_KEY": "pretend-key-for-tests"} if ai else {}
    llm = LLMRouter(env=env, store=store, transport=ai, sleep=lambda s: None)
    return Deps(tools=tools, store=store, llm=llm, today=TODAY, sleep=lambda s: None,
                ask_travel_mode=ask_travel_mode)


def _calls(log: list) -> dict:
    calls: dict = {}
    for name, args, result, error in log:
        calls.setdefault(name, []).append({"args": args, "result": result, "error": error})
    return calls


def run_change(request: str, changes: list[str], *, group: list | None = None) -> dict:
    """Plan a trip, then ask for the changes one after another.

    Returns {"before": the plan before the last change, "state": after it, "calls": every tool call,
    "calls_after": the calls the last change made, "ran": the worker agents the last change ran,
    "applied": whether the planner applied it}."""
    with offline():
        store = Store(":memory:")
        tools = RecordingClient()
        planner = Planner(_deps(tools, store))
        state = planner.start(request, group=group)
        if not state.get("itinerary"):
            raise PlanNotMade(f"no plan was made: {state.get('message', '')}")
        for number, text in enumerate(changes, 1):
            before, mark = _plain(state), len(tools.log)
            state = planner.resume(state["thread_id"], {"action": "revise", "feedback": text})
            if number < len(changes) and state.get("revisions", 0) == before.get("revisions", 0):
                raise PlanNotMade(f"the earlier change '{text}' was not applied: {state.get('message', '')}")
    after = _plain(state)
    ran = sorted({line["agent"] for line in after["log"][len(before["log"]):]}
                 & {"flight", "hotel", "weather", "activities"})
    return {"before": before, "state": after, "calls": _calls(tools.log), "calls_after": _calls(tools.log[mark:]),
            "ran": ran, "applied": after.get("revisions", 0) > before.get("revisions", 0)}


def run_trip(request: str, *, group: list | None = None, failures: dict | None = None,
             changes: list[str] | None = None, approve: bool = False, ask_travel_mode: bool = False,
             ai: dict | None = None, ask: str | None = None, live: dict | None = None) -> dict:
    """Run one trip, whatever its outcome (a question, a refusal or a plan).

    Returns {"state": ..., "calls": {tool name: [{"args", "result", "error"}, ...]}}."""
    pretend = PretendAI(ai) if ai is not None else None
    with offline(), recorded_live(live):
        store = Store(":memory:")
        tools = RecordingClient(failures)
        deps = _deps(tools, store, pretend, ask_travel_mode)
        planner = Planner(deps)
        state = planner.start(request, group=group)
        for text in changes or []:
            before = state.get("revisions", 0)
            state = planner.resume(state["thread_id"], {"action": "revise", "feedback": text})
            if state.get("revisions", 0) == before:
                raise PlanNotMade(f"the change '{text}' was not applied: {state.get('notice', '')}")
        if approve:
            state = planner.resume(state["thread_id"], {"action": "approve"})
        answer = chat_service.ai_answer(state, ask, deps.llm) if ask else None
    run = {"state": _plain(state), "calls": _calls(tools.log)}
    if pretend:
        run.update(ai_asked=sorted(set(pretend.asked)), chat_answer=answer)
    return run


def run_planner(request: str, changes: list[str] | None = None) -> dict:
    """The finished state for a request, after the change requests (if any)."""
    with offline():
        store = Store(":memory:")
        deps = Deps(tools=InProcessClient(), store=store, llm=LLMRouter(env={}, store=store), today=TODAY,
                    sleep=lambda s: None)
        planner = Planner(deps)
        state = planner.start(request)
        for text in changes or []:
            before = state.get("revisions", 0)
            state = planner.resume(state["thread_id"], {"action": "revise", "feedback": text})
            if state.get("revisions", 0) == before:
                raise PlanNotMade(f"the change '{text}' was not applied: {state.get('notice', '')}")
    if not state.get("itinerary") or not state.get("budget_report"):
        raise PlanNotMade(f"no plan was made (status {state.get('status')}): {state.get('message', '')}")
    return state
