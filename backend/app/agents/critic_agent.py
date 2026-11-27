"""Critic agent: deterministic feasibility checks on the finished plan."""
from __future__ import annotations

from app.core import config
from app.core.utils import fmt_inr
from app.graph.state import entry
from app.services import plan_checks as checks
from app.observability import recorder as observe


def critic_node(state: dict, deps) -> dict:
    issues = (checks.check_dates(state) + checks.check_hotel_nights(state) + checks.check_itinerary(state)
              + checks.verify_prices_and_totals(state))
    br = state["budget_report"]
    new_warnings: list[str] = []
    if br["incomplete"]:
        issues.append(checks.issue("warning", "partial_plan",
                                   f"Plan is incomplete: no {', '.join(br['incomplete'])} data."))
    blocking = [i for i in issues if i["severity"] == "blocking"]
    replan = "critic" if blocking and state.get("retries", 0) < config.MAX_AUTO_REPLANS else None
    if blocking and replan is None:
        new_warnings.append("Unresolved issue(s) after the retry limit: " + "; ".join(i["message"] for i in blocking))
    if br["over_budget"]:
        new_warnings.append(
            f"Estimated total {fmt_inr(br['total'])} is {fmt_inr(br['total'] - br['budget'])} over your "
            f"{fmt_inr(br['budget'])} budget" + (" even on the cheapest options." if state["strategy"] == "cheapest"
                                                 else " after the automatic retries."))
    if br["incomplete"]:
        new_warnings.append(f"Partial plan: {', '.join(br['incomplete'])} unavailable; totals understate the cost.")
    observe.event("guardrail", "critic_checks",
                  "blocking" if blocking else ("warnings" if issues else "ok"),
                  blocking=len(blocking), warnings=len(issues) - len(blocking), codes=[i["code"] for i in issues])
    return {"critic_issues": issues, "replan_reason": replan, "warnings": new_warnings,
            "log": [entry("critic", f"{len(blocking)} blocking, {len(issues) - len(blocking)} warning issue(s)")]}
