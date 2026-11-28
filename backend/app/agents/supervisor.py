"""Supervisor: decides which agents run (after a change, only those it affects), and picks a cheaper strategy on a
re-plan."""
from __future__ import annotations

from app.agents.common import WORKERS
from app.core import config
from app.core.utils import next_strategy
from app.graph.state import entry

# which searches a change request makes necessary (the day plan, budget and checks are always worked out again)
_PRICED = {"flight", "hotel", "activities"}
AFFECTS = {
    "budget": _PRICED, "strategy": _PRICED,
    "days": {"flight", "hotel", "weather"}, "month_day": {"flight", "hotel", "weather"},
    "destination": set(WORKERS), "travelers": {"flight", "hotel"}, "travel_mode": {"flight"},
    "cheaper_hotel": {"hotel"}, "cheaper_flight": {"flight"},
    "preferences_add": {"activities"}, "food_boost": {"activities"}, "exclude": {"activities"},
    "pace": set(),
}


def _worth_retrying(worker: str, block: dict | None) -> bool:
    """A result that is missing, failed or only a stand-in is never kept."""
    if not block or block.get("error"):
        return True
    return worker == "activities" and (
        block.get("data_quality") == "generic"
        or str((block.get("dining") or {}).get("note", "")).startswith("Restaurant lookup unavailable"))


def agents_for_changes(state: dict) -> list[str]:
    changed = state.get("changed")
    needed = set(_PRICED) if changed is None else set()
    for change in changed or []:
        needed |= AFFECTS.get(change, set(WORKERS))            # a kind of change not listed: run everything
    needed |= {w for w in _PRICED if _worth_retrying(w, state.get(w))}
    weather = state.get("weather")
    if not weather or weather.get("error"):
        needed.add("weather")
    return [w for w in WORKERS if w in needed]


def supervisor_node(state: dict, deps) -> dict:
    reason = state.get("replan_reason")
    retries = state.get("retries", 0)
    strategy = state.get("strategy", "normal")
    upd: dict = {"status": "running", "replan_reason": None}
    if reason is None:
        upd["fanout"] = list(WORKERS)
        msg = f"first pass: strategy={strategy}, workers={WORKERS}"
    else:
        upd.update(itinerary=None, budget_report=None, critic_issues=[], group_report=[], alternatives={})
        if reason != "feedback":
            upd.update(flight=None, hotel=None, activities=None)
        if reason == "over_budget":
            strategy = next_strategy(strategy)
            upd.update(strategy=strategy, retries=retries + 1, fanout=["flight", "hotel", "activities"])
            msg = f"replan (over budget): strategy -> {strategy}, retry {retries + 1}/{config.MAX_AUTO_REPLANS}"
        elif reason == "critic":
            upd.update(retries=retries + 1, fanout=list(WORKERS), weather=None)
            msg = f"replan (critic blocking issue): retry {retries + 1}/{config.MAX_AUTO_REPLANS}"
        else:                                                     # feedback
            fan = agents_for_changes(state)
            upd.update(retries=0, fanout=fan, **{w: None for w in fan if w != "weather"})
            kept = [w for w in WORKERS if w not in fan]
            repeat = [n for w in kept for n in (state.get(w) or {}).get("notices", [])
                      if n not in state.get("warnings", [])]
            if repeat:
                upd["warnings"] = repeat
            msg = (f"replan (user feedback): strategy={strategy}; searching again: {', '.join(fan) or 'nothing'}; "
                   f"kept: {', '.join(kept) or 'nothing'}")
    upd["log"] = [entry("supervisor", msg, reason=reason)]
    return upd
