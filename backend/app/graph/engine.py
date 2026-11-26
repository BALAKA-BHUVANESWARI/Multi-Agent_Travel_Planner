"""Pick the orchestration engine.

ENGINE=langgraph  -> LangGraph (error if not installed)
ENGINE=runner     -> dependency-free runner (always works; what the unit tests exercise)
ENGINE=auto       -> LangGraph if installed AND it passes a quick self-check, else runner
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import date

from app.database.repositories import Store
from app.graph.deps import Deps
from app.graph.runner import Planner
from app.services.llm_service import LLMRouter
from app.tools.client import InProcessClient


@contextmanager
def _offline():
    old = os.environ.get("REAL_DATA")
    os.environ["REAL_DATA"] = "0"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("REAL_DATA", None)
        else:
            os.environ["REAL_DATA"] = old


def graph_self_check() -> tuple[bool, str]:
    """Run a tiny offline plan -> approve cycle through LangGraph. Returns (ok, detail)."""
    try:
        from app.graph.workflow import GraphPlanner
        with _offline():
            store = Store(":memory:")
            deps = Deps(tools=InProcessClient(), store=store, llm=LLMRouter(env={}, store=store),
                        today=date(2026, 11, 24), sleep=lambda s: None)
            gp = GraphPlanner(deps)
            s = gp.start("Plan a 3 day trip to Goa from Delhi in January, budget 3 lakh for 2")
            if s.get("status") != "awaiting_approval":
                return False, f"unexpected status {s.get('status')}"
            s = gp.resume(s["thread_id"], {"action": "approve"})
            if s.get("status") != "booked":
                return False, f"unexpected final status {s.get('status')}"
        return True, "ok"
    except Exception as e:                                   # noqa: BLE001 (any failure -> fall back)
        return False, f"{type(e).__name__}: {e}"


def make_planner(engine: str | None = None, deps: Deps | None = None, db: str | None = None):
    engine = (engine or os.environ.get("ENGINE", "auto")).lower()
    deps = deps or Deps.default(db=db)
    if engine in ("auto", "langgraph"):
        try:
            import langgraph  # noqa: F401
        except ImportError:
            if engine == "langgraph":
                raise
        else:
            from app.graph.workflow import GraphPlanner
            if engine == "langgraph":
                return GraphPlanner(deps)
            ok, detail = graph_self_check()
            if ok:
                return GraphPlanner(deps)
            print(f"[travel-planner] LangGraph self-check failed ({detail}); using the built-in runner. "
                  "Set ENGINE=runner to silence this.", file=sys.stderr)
    planner = Planner(deps)
    planner.engine = "runner"
    return planner
