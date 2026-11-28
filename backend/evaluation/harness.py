"""Runs the real planner for an evaluation case: offline data, no AI, a fixed date, nothing saved to disk."""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date

from app.database.repositories import Store
from app.graph.deps import Deps
from app.graph.runner import Planner
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
