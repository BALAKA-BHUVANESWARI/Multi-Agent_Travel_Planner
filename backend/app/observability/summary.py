"""The few numbers and codes about a finished plan that go on a request's basic record. No places or text."""
from __future__ import annotations

# where an itinerary activity came from, read from its id
_SOURCES = (("wp-", "wikipedia"), ("wv-", "wikivoyage"), ("osm-", "openstreetmap"), ("gen", "generic"))


def _source(item_id: str) -> str:
    return next((name for prefix, name in _SOURCES if item_id.startswith(prefix)), "built_in")


def plan_summary(state: dict) -> dict:
    constraints = state.get("constraints") or {}
    report = state.get("budget_report") or {}
    sources: dict[str, int] = {}
    for day in (state.get("itinerary") or {}).get("days") or []:
        for item in day.get("items") or []:
            if item.get("type") == "activity" and item.get("id"):
                key = _source(str(item["id"]))
                sources[key] = sources.get(key, 0) + 1
    out = {"outcome": state.get("status"), "replans": state.get("retries", 0),
           "revisions": state.get("revisions", 0), "strategy": state.get("strategy"),
           "days": constraints.get("days"), "travelers": constraints.get("travelers"),
           "travel_mode": constraints.get("travel_mode"), "warnings": len(set(state.get("warnings") or [])),
           "critic_issues": len(state.get("critic_issues") or []), "activity_sources": sources}
    if report:
        out.update(over_budget=bool(report.get("over_budget")), incomplete=list(report.get("incomplete") or []))
    for key, name in (("flight", "transport_price"), ("hotel", "hotel_price")):
        picked = (state.get(key) or {}).get("selected")
        if picked:
            out[name] = "estimated" if picked.get("estimated", True) else "live"
    guard = state.get("guardrail") or {}
    if state.get("status") == "blocked":
        out["blocked_code"] = guard.get("code")
    return out


def run_status(state: dict) -> str:
    status = state.get("status")
    if status in ("blocked", "needs_info"):
        return status
    return "failed" if status in ("error", "failed") else "ok"
