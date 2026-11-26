"""Budget agent: totals the trip and asks for a cheaper re-plan when it is too expensive."""
from __future__ import annotations

from app.core import config
from app.core.utils import fmt_inr
from app.graph.state import entry
from app.services.budget_service import build_budget_report


def budget_node(state: dict, deps) -> dict:
    report = build_budget_report(state)
    over = report["over_budget"]
    replan = "over_budget" if over and state.get("retries", 0) < config.MAX_AUTO_REPLANS else None
    msg = f"total {fmt_inr(report['total'])} vs budget {fmt_inr(report['budget'])} ({'OVER' if over else 'ok'})"
    return {"budget_report": report, "replan_reason": replan, "log": [entry("budget", msg)]}
