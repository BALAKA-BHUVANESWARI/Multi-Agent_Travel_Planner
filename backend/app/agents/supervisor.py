"""Supervisor: decides which agents run, and picks a cheaper strategy on a re-plan."""
from __future__ import annotations

from app.agents.common import WORKERS
from app.core import config
from app.core.utils import next_strategy
from app.graph.state import entry


def supervisor_node(state: dict, deps) -> dict:
    reason = state.get("replan_reason")
    retries = state.get("retries", 0)
    strategy = state.get("strategy", "normal")
    upd: dict = {"status": "running", "replan_reason": None}
    if reason is None:
        upd["fanout"] = list(WORKERS)
        msg = f"first pass: strategy={strategy}, workers={WORKERS}"
    else:
        upd.update(flight=None, hotel=None, activities=None, itinerary=None, budget_report=None,
                   critic_issues=[], group_report=[], alternatives={})
        if reason == "over_budget":
            strategy = next_strategy(strategy)
            upd.update(strategy=strategy, retries=retries + 1, fanout=["flight", "hotel", "activities"])
            msg = f"replan (over budget): strategy -> {strategy}, retry {retries + 1}/{config.MAX_AUTO_REPLANS}"
        elif reason == "critic":
            upd.update(retries=retries + 1, fanout=list(WORKERS), weather=None)
            msg = f"replan (critic blocking issue): retry {retries + 1}/{config.MAX_AUTO_REPLANS}"
        else:                                                     # feedback
            fan = ["flight", "hotel", "activities"] + (["weather"] if not state.get("weather") else [])
            upd.update(retries=0, fanout=fan)
            msg = f"replan (user feedback): strategy={strategy}"
    upd["log"] = [entry("supervisor", msg, reason=reason)]
    return upd
